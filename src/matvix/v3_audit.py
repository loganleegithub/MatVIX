from __future__ import annotations

import math
import warnings
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.special import expit, logit
from scipy.stats import spearmanr
from sklearn.exceptions import ConvergenceWarning
from sklearn.metrics import roc_auc_score

from matvix.calendar import add_sessions, decision_as_of
from matvix.constants import EVENT_ORDER, LOGISTIC_FEATURES
from matvix.probability.baseline import beta_smoothed_base_rate
from matvix.probability.walk_forward import ProbabilitySpec, make_logistic
from matvix.storage import read_json, read_parquet, write_json, write_parquet
from matvix.v2_audit import _date_text, _finite, _sha256
from matvix.v2_audit import _split_name as _audit_window

AUDIT_VERSION = "3.0.0-stage-a"
CALIBRATION_DIAGNOSTICS = ("CURRENT_FREE_PLATT_504", "RAW_LOGISTIC_IDENTITY", "ROLLING_INTERCEPT_252")
AGE_LABELS = ("1-2", "3-5", "6-10", "11-20", "21-60", "61+")
AGE_BINS = (0, 2, 5, 10, 20, 60, math.inf)
PHASE_RISK_RANK = {
    "CARRY_SUPPORTIVE_LOW_STRESS": 0,
    "TAIL_RICH_QUIET_CURVE": 1,
    "REPAIR_IN_PROGRESS": 2,
    "MIXED_TRANSITION": 3,
    "FRONT_LOCALIZED_STRESS": 4,
    "PRESSURE_DIFFUSING": 5,
    "BROAD_PERSISTENT_STRESS": 6,
    "ACUTE_FRONT_STRESS": 7,
}


def _equal_count_reliability(frame: pd.DataFrame, probability_column: str) -> list[dict[str, Any]]:
    sample = frame.dropna(subset=["label", probability_column]).sort_values(
        [probability_column, "prediction_date"], kind="mergesort"
    )
    if sample.empty:
        return []
    records: list[dict[str, Any]] = []
    for number, positions in enumerate(np.array_split(np.arange(len(sample)), 5), start=1):
        if not len(positions):
            continue
        group = sample.iloc[positions]
        records.append(
            {
                "quintile": number,
                "samples": int(len(group)),
                "mean_probability": float(group[probability_column].mean()),
                "event_rate": float(group["label"].mean()),
                "first_prediction_date": _date_text(group["prediction_date"].min()),
                "last_prediction_date": _date_text(group["prediction_date"].max()),
            }
        )
    return records


def _probability_metrics(
    frame: pd.DataFrame,
    probability_column: str,
    *,
    tail: int | None = None,
) -> dict[str, Any]:
    sample = frame.dropna(subset=["label", probability_column, "base_rate_at_prediction"]).sort_values(
        "prediction_date"
    )
    if tail is not None:
        sample = sample.tail(tail)
    if sample.empty:
        return {"samples": 0}
    labels = sample["label"].to_numpy(dtype=float)
    probabilities = sample[probability_column].to_numpy(dtype=float)
    base_rates = sample["base_rate_at_prediction"].to_numpy(dtype=float)
    model_brier = float(np.mean((probabilities - labels) ** 2))
    base_brier = float(np.mean((base_rates - labels) ** 2))
    reliability = _equal_count_reliability(sample, probability_column)
    ece = float(
        sum(row["samples"] / len(sample) * abs(row["mean_probability"] - row["event_rate"]) for row in reliability)
    )
    positives = int(labels.sum())
    negatives = int(len(labels) - positives)
    auc = float(roc_auc_score(labels, probabilities)) if positives and negatives else None
    return {
        "samples": int(len(sample)),
        "positives": positives,
        "negatives": negatives,
        "first_prediction_date": _date_text(sample["prediction_date"].min()),
        "last_prediction_date": _date_text(sample["prediction_date"].max()),
        "brier_model": model_brier,
        "brier_base": base_brier,
        "brier_skill": float(1.0 - model_brier / base_brier) if base_brier > 0 else None,
        "ece": ece,
        "auc": auc,
        "mean_probability": float(probabilities.mean()),
        "event_rate": float(labels.mean()),
        "reliability_quintiles": reliability,
    }


def _fit_fixed_intercept(raw_probabilities: pd.Series, labels: pd.Series) -> float:
    clipped = np.clip(raw_probabilities.to_numpy(dtype=float), 1e-6, 1 - 1e-6)
    z = logit(clipped)
    y = labels.to_numpy(dtype=float)

    def score(intercept: float) -> float:
        return float(np.mean(expit(z + intercept)) - np.mean(y))

    return float(brentq(score, -40.0, 40.0))


def append_calibration_replay(event_oof: pd.DataFrame) -> pd.DataFrame:
    """Replay V2 Platt cohorts and the one frozen V3 calibration diagnostic."""

    result = event_oof.sort_values("prediction_date").reset_index(drop=True).copy()
    result["rolling_intercept_probability"] = result["base_probability"].astype(float)
    result["rolling_intercept_b"] = np.nan
    result["rolling_intercept_method"] = "IDENTITY_WARMUP"
    result["rolling_intercept_samples"] = 0
    result["rolling_intercept_positive"] = 0
    result["rolling_intercept_negative"] = 0
    result["free_platt_expected_samples"] = 0
    result["free_platt_calibration_positive"] = 0
    result["free_platt_calibration_negative"] = 0
    result["free_platt_arithmetic_error"] = np.nan

    for index, row in result.iterrows():
        prediction_date = pd.Timestamp(row["prediction_date"]).normalize()
        as_of = pd.Timestamp(decision_as_of(prediction_date)).tz_convert("UTC")
        prior = result.iloc[:index].loc[
            result.iloc[:index]["label_status"].isin(["OBSERVED_0", "OBSERVED_1"])
            & (pd.to_datetime(result.iloc[:index]["outcome_available_at"], utc=True) <= as_of)
        ]
        free_prior = prior.tail(504)
        result.at[index, "free_platt_expected_samples"] = len(free_prior)
        result.at[index, "free_platt_calibration_positive"] = int(free_prior["label"].sum())
        result.at[index, "free_platt_calibration_negative"] = int(len(free_prior) - free_prior["label"].sum())
        if (
            bool(row.get("calibration_converged"))
            and pd.notna(row.get("calibrated_probability"))
            and pd.notna(row.get("platt_a"))
            and pd.notna(row.get("platt_b"))
        ):
            expected = float(
                np.clip(
                    expit(float(row["platt_a"]) * float(row["decision_score"]) + float(row["platt_b"])),
                    1e-6,
                    1 - 1e-6,
                )
            )
            result.at[index, "free_platt_arithmetic_error"] = abs(expected - float(row["calibrated_probability"]))

        intercept_prior = prior.tail(252)
        positives = int(intercept_prior["label"].sum()) if not intercept_prior.empty else 0
        negatives = len(intercept_prior) - positives
        result.at[index, "rolling_intercept_samples"] = len(intercept_prior)
        result.at[index, "rolling_intercept_positive"] = positives
        result.at[index, "rolling_intercept_negative"] = negatives
        if len(intercept_prior) < 40 or positives < 20 or negatives < 20:
            continue
        intercept = _fit_fixed_intercept(intercept_prior["base_probability"], intercept_prior["label"])
        raw = float(np.clip(row["base_probability"], 1e-6, 1 - 1e-6))
        probability = float(np.clip(expit(logit(raw) + intercept), 1e-6, 1 - 1e-6))
        result.at[index, "rolling_intercept_probability"] = probability
        result.at[index, "rolling_intercept_b"] = intercept
        result.at[index, "rolling_intercept_method"] = "ROLLING_INTERCEPT_252"
    return result


def _score_scale_by_year(frame: pd.DataFrame) -> dict[str, Any]:
    records: dict[str, Any] = {}
    for year, group in frame.groupby(pd.to_datetime(frame["prediction_date"]).dt.year):
        records[str(year)] = {
            "samples": int(len(group)),
            "decision_score_mean": float(group["decision_score"].mean()),
            "decision_score_std": float(group["decision_score"].std(ddof=0)),
            "decision_score_min": float(group["decision_score"].min()),
            "decision_score_max": float(group["decision_score"].max()),
            "raw_probability_mean": float(group["base_probability"].mean()),
            "base_rate_mean": _finite(group["base_rate_at_prediction"].mean()),
        }
    return records


def _metric_strata(frame: pd.DataFrame, probability_column: str) -> dict[str, Any]:
    windows = {name: _probability_metrics(group, probability_column) for name, group in frame.groupby("audit_window")}
    annual = {
        str(year): _probability_metrics(group, probability_column)
        for year, group in frame.groupby(pd.to_datetime(frame["prediction_date"]).dt.year)
    }
    regimes = {name: _probability_metrics(group, probability_column) for name, group in frame.groupby("weather_regime")}
    return {"windows": windows, "annual": annual, "weather_regimes": regimes}


def _warmup_breakdown(frame: pd.DataFrame) -> dict[str, int]:
    counts = {
        "raw_oof": int(len(frame)),
        "calibrated_oof": int(frame["calibrated_probability"].notna().sum()),
        "insufficient_total": 0,
        "insufficient_positive": 0,
        "insufficient_negative": 0,
        "fit_nonconvergence": 0,
        "other": 0,
    }
    for row in frame.loc[frame["calibrated_probability"].isna()].itertuples(index=False):
        samples = int(row.free_platt_expected_samples)
        positives = int(row.free_platt_calibration_positive)
        negatives = int(row.free_platt_calibration_negative)
        if samples < 40:
            counts["insufficient_total"] += 1
        elif positives < 20:
            counts["insufficient_positive"] += 1
        elif negatives < 20:
            counts["insufficient_negative"] += 1
        elif not bool(row.calibration_converged):
            counts["fit_nonconvergence"] += 1
        else:
            counts["other"] += 1
    return counts


def _calibration_audit(
    daily: pd.DataFrame, targets: pd.DataFrame, oof: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, pd.DataFrame]]:
    result = daily.copy()
    diagnostics: dict[str, Any] = {}
    replayed: dict[str, pd.DataFrame] = {}
    state_regime = result.set_index("session_date")["weather_regime"]
    for event in EVENT_ORDER:
        event_oof = append_calibration_replay(oof.loc[oof["event_id"].eq(event)].copy())
        event_oof["audit_window"] = _audit_window(event_oof["prediction_date"])
        event_oof["weather_regime"] = pd.to_datetime(event_oof["prediction_date"]).map(state_regime)
        replayed[event] = event_oof
        completed = event_oof.loc[event_oof["label_status"].isin(["OBSERVED_0", "OBSERVED_1"])].copy()
        methods = {
            "CURRENT_FREE_PLATT_504": "calibrated_probability",
            "RAW_LOGISTIC_IDENTITY": "base_probability",
            "ROLLING_INTERCEPT_252": "rolling_intercept_probability",
            "FROZEN_CAUSAL_BASE_RATE": "base_rate_at_prediction",
        }
        latest = {name: _probability_metrics(completed, column, tail=252) for name, column in methods.items()}
        method_strata = {name: _metric_strata(completed, column) for name, column in methods.items()}
        latest_completed_dates = set(
            pd.to_datetime(completed.sort_values("prediction_date").tail(252)["prediction_date"])
        )
        latest_rows = event_oof.loc[pd.to_datetime(event_oof["prediction_date"]).isin(latest_completed_dates)]
        negative = event_oof["platt_a"].lt(0)
        negative_latest = latest_rows["platt_a"].lt(0)
        arithmetic = event_oof["free_platt_arithmetic_error"].dropna()
        target = targets.loc[targets["event_id"].eq(event)]
        diagnostics[event] = {
            "target_rows": int(len(target)),
            "completed_targets": int(target["label_status"].isin(["OBSERVED_0", "OBSERVED_1"]).sum()),
            "raw_oof": int(len(event_oof)),
            "calibrated_oof": int(event_oof["calibrated_probability"].notna().sum()),
            "first_raw_oof": _date_text(event_oof["prediction_date"].min()),
            "first_calibrated_oof": _date_text(
                event_oof.loc[event_oof["calibrated_probability"].notna(), "prediction_date"].min()
            ),
            "latest_252": latest,
            "strata": method_strata,
            "score_scale_by_year": _score_scale_by_year(event_oof),
            "negative_platt_slope": {
                "all_rows": int(negative.sum()),
                "latest_252_completed": int(negative_latest.sum()),
                "first_date": _date_text(event_oof.loc[negative, "prediction_date"].min()),
                "last_date": _date_text(event_oof.loc[negative, "prediction_date"].max()),
            },
            "free_platt_arithmetic": {
                "rows_replayed": int(len(arithmetic)),
                "maximum_absolute_error": _finite(arithmetic.max()),
                "calibration_sample_count_mismatches": int(
                    event_oof["free_platt_expected_samples"].ne(event_oof["calibration_samples"]).sum()
                ),
            },
            "warmup_breakdown": _warmup_breakdown(event_oof),
            "calibration_history_lag": {
                "latest_252_label_rate": _finite(completed.sort_values("prediction_date").tail(252)["label"].mean()),
                "latest_252_base_rate_mean": _finite(
                    completed.sort_values("prediction_date").tail(252)["base_rate_at_prediction"].mean()
                ),
                "latest_252_free_platt_cohort_rate_mean": _finite(
                    (
                        latest_rows["free_platt_calibration_positive"]
                        / latest_rows["free_platt_expected_samples"].replace(0, np.nan)
                    ).mean()
                ),
            },
        }
        merge_columns = [
            "prediction_date",
            "decision_score",
            "base_probability",
            "base_rate_at_prediction",
            "calibrated_probability",
            "platt_a",
            "platt_b",
            "calibration_samples",
            "calibration_converged",
            "free_platt_expected_samples",
            "free_platt_calibration_positive",
            "free_platt_calibration_negative",
            "free_platt_arithmetic_error",
            "rolling_intercept_probability",
            "rolling_intercept_b",
            "rolling_intercept_method",
            "rolling_intercept_samples",
            "rolling_intercept_positive",
            "rolling_intercept_negative",
        ]
        renamed = event_oof[merge_columns].rename(
            columns={column: f"{event}__{column}" for column in merge_columns if column != "prediction_date"}
        )
        renamed = renamed.rename(columns={"prediction_date": "session_date"})
        result = result.merge(renamed, on="session_date", how="left", validate="one_to_one")
    summary = {
        "diagnostics_compared": list(CALIBRATION_DIAGNOSTICS),
        "rolling_intercept_history_status": "ECONOMIC_HISTORY_CONTAMINATED_DIAGNOSTIC",
        "events": diagnostics,
    }
    return result, summary, replayed


def _spell_columns(statuses: pd.Series) -> tuple[pd.Series, pd.Series]:
    ages: list[int | None] = []
    spell_ids: list[int | None] = []
    age = 0
    current_spell = 0
    for status in statuses.astype(str):
        if status == "ELIGIBLE":
            if age == 0:
                current_spell += 1
            age += 1
            ages.append(age)
            spell_ids.append(current_spell)
        else:
            age = 0
            ages.append(None)
            spell_ids.append(None)
    return (
        pd.Series(ages, index=statuses.index, dtype="Int64"),
        pd.Series(spell_ids, index=statuses.index, dtype="Int64"),
    )


def _prediction_cluster_summary(daily_dates: pd.Series, prediction_dates: pd.Series) -> dict[str, int]:
    _, cluster_ids = _spell_columns(pd.Series(np.where(daily_dates.isin(pd.to_datetime(prediction_dates)), "ELIGIBLE", "NOT_APPLICABLE")))
    lengths = cluster_ids.value_counts()
    return {"clusters": int(len(lengths)), "maximum_sessions": int(lengths.max()) if not lengths.empty else 0}


def _causal_coupling_residual(
    vix: pd.Series,
    vvix: pd.Series,
    *,
    maximum: int = 756,
    minimum: int = 504,
) -> pd.Series:
    x = np.log(pd.to_numeric(vix, errors="coerce"))
    y = np.log(pd.to_numeric(vvix, errors="coerce"))
    residuals = pd.Series(np.nan, index=vix.index, dtype=float)
    for index in range(len(vix)):
        prior = pd.DataFrame({"x": x.iloc[:index], "y": y.iloc[:index]}).dropna().tail(maximum)
        if len(prior) < minimum or pd.isna(x.iloc[index]) or pd.isna(y.iloc[index]):
            continue
        design = np.column_stack([np.ones(len(prior)), prior["x"].to_numpy(dtype=float)])
        coefficients, *_ = np.linalg.lstsq(design, prior["y"].to_numpy(dtype=float), rcond=None)
        expected = coefficients[0] + coefficients[1] * float(x.iloc[index])
        residuals.iloc[index] = float(y.iloc[index] - expected)
    return residuals


def _prepare_daily_facts(states: pd.DataFrame, targets: pd.DataFrame) -> pd.DataFrame:
    daily = states.sort_values("session_date").reset_index(drop=True).copy()
    daily["session_date"] = pd.to_datetime(daily["session_date"]).dt.normalize()
    daily["audit_window"] = _audit_window(daily["session_date"])
    crisis = (
        daily["hard_acute"].eq(True)
        | daily["front_slope30"].lt(0)
        | daily["broad_pressure_day"].eq(True)
        | daily["carry_environment_state"].eq("CLOSED")
    )
    calm = (
        daily["carry_answer"].eq("SUPPORTIVE")
        & daily["shock_answer"].eq("CALM")
        & daily["persistence_answer"].eq("NORMAL")
    )
    daily["weather_regime"] = np.select([crisis, calm], ["CRISIS", "CALM"], default="TRANSITION")

    target_columns = [
        "prediction_date",
        "event_status",
        "label",
        "label_status",
        "outcome_available_at",
        "valid_through_session",
    ]
    for event in EVENT_ORDER:
        event_targets = targets.loc[targets["event_id"].eq(event), target_columns].copy()
        event_targets = event_targets.rename(
            columns={
                "prediction_date": "session_date",
                **{column: f"{event}__{column}" for column in target_columns if column != "prediction_date"},
            }
        )
        event_targets["session_date"] = pd.to_datetime(event_targets["session_date"]).dt.normalize()
        daily = daily.merge(event_targets, on="session_date", how="left", validate="one_to_one")

    carry_event = "carry_environment_recovers_10d"
    broad_event = "broad_stress_persists_10d"
    carry_age, carry_spell = _spell_columns(daily[f"{carry_event}__event_status"])
    broad_age, broad_spell = _spell_columns(daily[f"{broad_event}__event_status"])
    daily["carry_spell_age"] = carry_age
    daily["carry_spell_id"] = carry_spell
    daily["log1p_carry_spell_age"] = np.log1p(carry_age.astype(float))
    daily["carry_recovering_flag"] = np.where(
        carry_age.notna(), daily["carry_environment_state"].eq("RECOVERING").astype(float), np.nan
    )
    daily["broad_spell_age"] = broad_age
    daily["broad_spell_id"] = broad_spell
    daily["log1p_broad_spell_age"] = np.log1p(broad_age.astype(float))

    broad_known = daily["broad_pressure_day"].map(
        lambda value: np.nan if value is None or pd.isna(value) else float(bool(value))
    )
    daily["broad_days_last_5"] = broad_known.rolling(5, min_periods=5).sum()
    daily["broad_days_last_10"] = broad_known.rolling(10, min_periods=10).sum()
    daily["d1_log_vvix"] = np.log(daily["vvix_close"] / daily["vvix_close"].shift(1))
    daily["spx_5d_log_momentum"] = np.log(daily["spx_close"] / daily["spx_close"].shift(5))
    daily["vvix_vix_coupling_residual"] = _causal_coupling_residual(daily["vix_close"], daily["vvix_close"])
    daily["vix9d_vix_convergence_5d"] = daily["d5_near_stress"]
    daily["vvix_collapse_5d"] = -daily["d5_log_vvix"]
    daily["negative_front_slope30"] = -daily["front_slope30"]
    daily["negative_d5_front_slope30"] = -daily["d5_front_slope30"]
    daily["negative_basis30_eod"] = -daily["basis30_eod"]
    return daily


def _completed_before(
    merged: pd.DataFrame,
    prediction_date: pd.Timestamp,
    *,
    purge_sessions: int | None,
) -> pd.DataFrame:
    as_of = pd.Timestamp(decision_as_of(prediction_date)).tz_convert("UTC")
    completed = merged.loc[
        merged["label_status"].isin(["OBSERVED_0", "OBSERVED_1"])
        & (pd.to_datetime(merged["outcome_available_at"], utc=True) <= as_of)
        & (pd.to_datetime(merged["prediction_date"]) < prediction_date)
    ]
    if purge_sessions is not None:
        cutoff = add_sessions(prediction_date, -purge_sessions)
        completed = completed.loc[pd.to_datetime(completed["prediction_date"]) <= cutoff]
    return completed.sort_values("prediction_date")


def build_fixed_candidate_oof(
    daily: pd.DataFrame,
    targets: pd.DataFrame,
    event: str,
    features: list[str],
    *,
    spec: ProbabilitySpec | None = None,
) -> pd.DataFrame:
    """Build one audit-only, predeclared candidate with the frozen V2 fit contract."""

    spec = spec or ProbabilitySpec()
    source = daily[["session_date", *features]].rename(columns={"session_date": "prediction_date"})
    event_targets = targets.loc[targets["event_id"].eq(event)].copy()
    merged = event_targets.merge(source, on="prediction_date", how="left").sort_values("prediction_date")
    records: list[dict[str, Any]] = []
    for _, row in merged.iterrows():
        if row["event_status"] != "ELIGIBLE":
            continue
        prediction_date = pd.Timestamp(row["prediction_date"]).normalize()
        training = _completed_before(merged, prediction_date, purge_sessions=spec.purge_sessions)
        completed = _completed_before(merged, prediction_date, purge_sessions=None)
        training = training.dropna(subset=[*features, "label"]).tail(spec.training_max)
        positives = int(training["label"].sum()) if not training.empty else 0
        negatives = len(training) - positives
        base_rate, base_samples, base_positive, base_negative = beta_smoothed_base_rate(
            completed["label"],
            max_samples=spec.base_rate_max,
            minimum_samples=spec.base_rate_min,
        )
        if (
            len(training) < spec.training_min
            or positives < spec.training_min_positive
            or negatives < spec.training_min_negative
            or row[features].isna().any()
        ):
            continue
        model = make_logistic()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ConvergenceWarning)
            model.fit(
                training[features].to_numpy(dtype=float),
                training["label"].to_numpy(dtype=int),
            )
        converged = not any(issubclass(item.category, ConvergenceWarning) for item in caught)
        if not converged:
            continue
        values = row[features].to_numpy(dtype=float).reshape(1, -1)
        label_observed = row["label_status"] in ("OBSERVED_0", "OBSERVED_1")
        records.append(
            {
                "event_id": event,
                "prediction_date": prediction_date,
                "outcome_available_at": row["outcome_available_at"],
                "label": int(row["label"]) if label_observed else np.nan,
                "label_status": row["label_status"],
                "decision_score": float(model.decision_function(values)[0]),
                "base_probability": float(model.predict_proba(values)[0, 1]),
                "base_rate_at_prediction": base_rate,
                "base_rate_samples": base_samples,
                "base_rate_positive": base_positive,
                "base_rate_negative": base_negative,
                "training_samples": len(training),
                "training_positive": positives,
                "training_negative": negatives,
                "training_latest_prediction_date": training["prediction_date"].max(),
                "training_latest_outcome_available_at": training["outcome_available_at"].max(),
                "calibrated_probability": np.nan,
                "platt_a": np.nan,
                "platt_b": np.nan,
                "calibration_samples": 0,
                "calibration_converged": False,
            }
        )
    return append_calibration_replay(pd.DataFrame(records))


def _feature_direction(frame: pd.DataFrame, feature: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    signs: list[int] = []
    for name, group in frame.groupby("audit_window"):
        sample = group.dropna(subset=[feature, "label"])
        positives = sample.loc[sample["label"].eq(1), feature]
        negatives = sample.loc[sample["label"].eq(0), feature]
        difference = float(positives.mean() - negatives.mean()) if not positives.empty and not negatives.empty else None
        correlation = (
            float(spearmanr(sample[feature], sample["label"]).statistic)
            if len(sample) >= 3 and sample[feature].nunique() > 1 and sample["label"].nunique() > 1
            else None
        )
        sign = 0 if difference is None or difference == 0 else (1 if difference > 0 else -1)
        if name in {"DEVELOPMENT", "CONFIRMATION"} and sign:
            signs.append(sign)
        result[str(name)] = {
            "samples": int(len(sample)),
            "positive_mean": _finite(positives.mean()),
            "negative_mean": _finite(negatives.mean()),
            "positive_minus_negative": difference,
            "spearman": correlation,
            "sign": sign,
        }
    result["two_window_direction_stable"] = bool(len(signs) == 2 and signs[0] == signs[1])
    return result


def _leave_one_spell_direction(frame: pd.DataFrame, feature: str, spell_column: str) -> dict[str, Any]:
    sample = frame.dropna(subset=[feature, "label", spell_column]).copy()
    if sample.empty or sample[spell_column].nunique() < 2:
        return {"status": "INSUFFICIENT_EVIDENCE", "spells": 0}
    overall = float(spearmanr(sample[feature], sample["label"]).statistic)
    signs: list[int] = []
    correlations: list[float] = []
    for spell_id in sample[spell_column].unique():
        left = sample.loc[sample[spell_column].ne(spell_id)]
        if left[feature].nunique() < 2 or left["label"].nunique() < 2:
            continue
        correlation = float(spearmanr(left[feature], left["label"]).statistic)
        if math.isfinite(correlation):
            correlations.append(correlation)
            signs.append(0 if correlation == 0 else (1 if correlation > 0 else -1))
    expected_sign = 0 if overall == 0 else (1 if overall > 0 else -1)
    consistent = sum(sign == expected_sign for sign in signs)
    return {
        "status": "PASS" if signs and consistent == len(signs) else "UNSTABLE",
        "spells": int(sample[spell_column].nunique()),
        "overall_spearman": overall,
        "leave_one_spell_runs": len(signs),
        "same_direction_runs": consistent,
        "same_direction_rate": float(consistent / len(signs)) if signs else None,
        "minimum_spearman": min(correlations) if correlations else None,
        "maximum_spearman": max(correlations) if correlations else None,
    }


def _candidate_model_comparison(candidate: pd.DataFrame, baseline: pd.DataFrame) -> dict[str, Any]:
    candidate_completed = candidate.loc[candidate["label_status"].isin(["OBSERVED_0", "OBSERVED_1"])].copy()
    baseline_columns = baseline[["prediction_date", "base_probability"]].rename(
        columns={"base_probability": "v2_raw_probability"}
    )
    common = candidate_completed.merge(
        baseline_columns, on="prediction_date", how="inner", validate="one_to_one"
    ).sort_values("prediction_date")
    common_latest = common.tail(252)
    latest = {
        "candidate_raw": _probability_metrics(candidate_completed, "base_probability", tail=252),
        "candidate_rolling_intercept": _probability_metrics(
            candidate_completed, "rolling_intercept_probability", tail=252
        ),
        "common_v2_raw": _probability_metrics(common_latest, "v2_raw_probability"),
        "common_candidate_raw": _probability_metrics(common_latest, "base_probability"),
        "common_candidate_rolling_intercept": _probability_metrics(common_latest, "rolling_intercept_probability"),
    }
    windows = {
        name: {
            "candidate_raw": _probability_metrics(group, "base_probability"),
            "candidate_rolling_intercept": _probability_metrics(group, "rolling_intercept_probability"),
        }
        for name, group in candidate_completed.assign(
            audit_window=_audit_window(candidate_completed["prediction_date"])
        ).groupby("audit_window")
    }
    prediction = pd.to_datetime(candidate["prediction_date"])
    purge_cutoff = prediction.map(lambda value: add_sessions(value, -20))
    latest_training = pd.to_datetime(candidate["training_latest_prediction_date"])
    training_outcome = pd.to_datetime(candidate["training_latest_outcome_available_at"], utc=True)
    prediction_as_of = prediction.map(lambda value: pd.Timestamp(decision_as_of(value)).tz_convert("UTC"))
    return {
        "raw_oof_rows": int(len(candidate)),
        "completed_oof_rows": int(len(candidate_completed)),
        "first_raw_oof": _date_text(candidate["prediction_date"].min()),
        "first_rolling_intercept": _date_text(
            candidate.loc[
                candidate["rolling_intercept_method"].eq("ROLLING_INTERCEPT_252"),
                "prediction_date",
            ].min()
        ),
        "latest_252": latest,
        "windows": windows,
        "pit_integrity": {
            "purge_boundary_violations": int(latest_training.gt(purge_cutoff).sum()),
            "outcome_availability_violations": int(training_outcome.gt(prediction_as_of).sum()),
        },
    }


def _age_rate_table(completed: pd.DataFrame, age_column: str, spell_column: str) -> dict[str, Any]:
    sample = completed.dropna(subset=[age_column, "label"]).copy()
    sample["age_bucket"] = pd.cut(
        sample[age_column].astype(float),
        bins=AGE_BINS,
        labels=AGE_LABELS,
        include_lowest=True,
        right=True,
    )
    records: dict[str, Any] = {}
    for window, window_group in sample.groupby("audit_window"):
        rows: dict[str, Any] = {}
        for bucket in AGE_LABELS:
            group = window_group.loc[window_group["age_bucket"].astype(str).eq(bucket)]
            rows[bucket] = {
                "samples": int(len(group)),
                "positives": int(group["label"].sum()) if not group.empty else 0,
                "event_rate": _finite(group["label"].mean()),
                "spells": int(group[spell_column].nunique()) if not group.empty else 0,
            }
        records[str(window)] = rows
    return records


def _carry_audit(
    daily: pd.DataFrame,
    targets: pd.DataFrame,
    baseline_oof: pd.DataFrame,
) -> tuple[dict[str, Any], pd.DataFrame]:
    event = "carry_environment_recovers_10d"
    label_column = f"{event}__label"
    status_column = f"{event}__label_status"
    completed = daily.loc[daily[status_column].isin(["OBSERVED_0", "OBSERVED_1"])].copy()
    completed["label"] = completed[label_column].astype(float)
    completed["prediction_date"] = completed["session_date"]
    existing_predictor = f"{event}__base_probability"
    completed["v2_raw_residual"] = completed["label"] - completed[existing_predictor]

    duration_features = [*LOGISTIC_FEATURES[event], "log1p_carry_spell_age", "carry_recovering_flag"]
    candidate = build_fixed_candidate_oof(daily, targets, event, duration_features)
    baseline_event = baseline_oof.loc[baseline_oof["event_id"].eq(event)].copy()
    age_rates = _age_rate_table(completed, "carry_spell_age", "carry_spell_id")
    state_rates = {
        str(state): {
            "samples": int(len(group)),
            "positives": int(group["label"].sum()),
            "event_rate": float(group["label"].mean()),
        }
        for state, group in completed.groupby("carry_environment_state")
    }
    directions = {
        feature: _feature_direction(completed, feature)
        for feature in (
            "log1p_carry_spell_age",
            "carry_recovering_flag",
            "repair_scaled",
            "vix9d_vix_convergence_5d",
            "vvix_collapse_5d",
            "vrp_ewma94",
            "spx_5d_log_momentum",
        )
    }
    latest = completed.sort_values("session_date").tail(252)
    spell_shares = latest["carry_spell_id"].value_counts(normalize=True)
    residual_by_age: dict[str, Any] = {}
    age_buckets = pd.cut(
        completed["carry_spell_age"].astype(float),
        bins=AGE_BINS,
        labels=AGE_LABELS,
        include_lowest=True,
    )
    for bucket in AGE_LABELS:
        residuals = completed.loc[age_buckets.astype(str).eq(bucket), "v2_raw_residual"]
        residual_by_age[bucket] = {
            "samples": int(residuals.notna().sum()),
            "mean_label_minus_raw_probability": _finite(residuals.mean()),
        }
    summary = {
        "event_semantics_changed": False,
        "eligible_spells": int(daily["carry_spell_id"].nunique()),
        "maximum_spell_length": int(daily["carry_spell_age"].max()),
        "age_conditioned_recovery": age_rates,
        "state_conditioned_recovery": state_rates,
        "leave_one_spell_out_duration_direction": _leave_one_spell_direction(
            completed, "log1p_carry_spell_age", "carry_spell_id"
        ),
        "feature_directions": directions,
        "v2_raw_residual_by_age": residual_by_age,
        "latest_252_spell_concentration": {
            "spells": int(latest["carry_spell_id"].nunique()),
            "largest_spell_share": _finite(spell_shares.max()),
            "age_61_plus_share": float(latest["carry_spell_age"].ge(61).mean()),
        },
        "fixed_model_comparison": _candidate_model_comparison(candidate, baseline_event),
        "candidate_features": duration_features,
        "hazard_claim": "DURATION_CONDITIONED_FIXED_10D_LOGISTIC_NOT_SURVIVAL_MODEL",
    }
    return summary, candidate


def _broad_5d_label(daily: pd.DataFrame) -> pd.Series:
    event = "broad_stress_persists_10d"
    eligible = daily[f"{event}__event_status"].eq("ELIGIBLE")
    values = daily["broad_pressure_day"].map(
        lambda value: np.nan if value is None or pd.isna(value) else float(bool(value))
    )
    labels = pd.Series(np.nan, index=daily.index, dtype=float)
    for index in daily.index[eligible]:
        future = values.iloc[int(index) + 1 : int(index) + 6]
        if len(future) == 5 and future.notna().all():
            labels.iloc[int(index)] = float(future.sum() >= 3)
    return labels


def _broad_audit(
    daily: pd.DataFrame,
    targets: pd.DataFrame,
    baseline_oof: pd.DataFrame,
    calibration_summary: dict[str, Any],
) -> tuple[dict[str, Any], pd.DataFrame]:
    event = "broad_stress_persists_10d"
    label_column = f"{event}__label"
    status_column = f"{event}__label_status"
    completed = daily.loc[daily[status_column].isin(["OBSERVED_0", "OBSERVED_1"])].copy()
    completed["label"] = completed[label_column].astype(float)
    completed["prediction_date"] = completed["session_date"]
    duration_features = [*LOGISTIC_FEATURES[event], "log1p_broad_spell_age", "broad_days_last_5", "broad_days_last_10"]
    candidate = build_fixed_candidate_oof(daily, targets, event, duration_features)
    baseline_event = baseline_oof.loc[baseline_oof["event_id"].eq(event)].copy()
    directions = {
        feature: _feature_direction(completed, feature)
        for feature in (
            "log1p_broad_spell_age",
            "broad_days_last_5",
            "broad_days_last_10",
            "f4_f7_inversion_share",
            "f4_f7_level",
            "f4_f7_slope30",
            "d5_log_f4_f7_level",
            "d5_f4_f7_slope30",
        )
    }
    labels_5d = _broad_5d_label(daily)
    common = daily.loc[labels_5d.notna() & daily[label_column].notna()].copy()
    common["broad_5d_label"] = labels_5d.loc[common.index]
    common["broad_10d_label"] = common[label_column].astype(float)
    target = targets.loc[targets["event_id"].eq(event)]
    raw_rows = int(len(baseline_event))
    calibrated_rows = int(baseline_event["calibrated_probability"].notna().sum())
    summary = {
        "event_semantics_changed": False,
        "target_counts": {str(key): int(value) for key, value in target["label_status"].value_counts().items()},
        "raw_oof": raw_rows,
        "calibrated_oof": calibrated_rows,
        "raw_to_calibrated_difference": raw_rows - calibrated_rows,
        "warmup_breakdown": calibration_summary["events"][event]["warmup_breakdown"],
        "event_cluster_counts": {
            "all_completed_targets": _prediction_cluster_summary(daily["session_date"], completed["session_date"]),
            "raw_oof": _prediction_cluster_summary(daily["session_date"], baseline_event["prediction_date"]),
            "calibrated_oof": _prediction_cluster_summary(daily["session_date"], baseline_event.loc[baseline_event["calibrated_probability"].notna(), "prediction_date"]),
            "latest_252_raw_oof": _prediction_cluster_summary(daily["session_date"], baseline_event.tail(252)["prediction_date"]),
        },
        "overlapping_label_row_ratio": float(
            1.0 - daily["broad_spell_id"].nunique() / max(daily[f"{event}__event_status"].eq("ELIGIBLE").sum(), 1)
        ),
        "age_conditioned_persistence": _age_rate_table(completed, "broad_spell_age", "broad_spell_id"),
        "leave_one_cluster_out_duration_direction": _leave_one_spell_direction(
            completed, "log1p_broad_spell_age", "broad_spell_id"
        ),
        "feature_directions": directions,
        "fixed_direct_10d_model_comparison": _candidate_model_comparison(candidate, baseline_event),
        "candidate_features": duration_features,
        "auxiliary_5d_horizon": {
            "definition": "AUDIT_ONLY_AT_LEAST_3_BROAD_DAYS_IN_NEXT_5",
            "common_completed": int(len(common)),
            "agreement_with_direct_10d": _finite(common["broad_5d_label"].eq(common["broad_10d_label"]).mean()),
            "five_day_only_positive": int((common["broad_5d_label"].eq(1) & common["broad_10d_label"].eq(0)).sum()),
            "ten_day_only_positive": int((common["broad_5d_label"].eq(0) & common["broad_10d_label"].eq(1)).sum()),
            "causal_predictor_at_t": False,
            "conclusion": "OVERLAPPING_FUTURE_LABEL_NOT_INDEPENDENT_10D_EVIDENCE",
        },
        "bayesian_or_hierarchical": {
            "evaluated_as_initial_repair": False,
            "reason": "CANNOT_CREATE_ACTUAL_PUBLISHED_OOF_OR_NEW_DIRECT_10D_INFORMATION",
        },
    }
    return summary, candidate


def _fragility_target_ledger(daily: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for index, row in daily.iterrows():
        prediction_date = pd.Timestamp(row["session_date"]).normalize()
        answers = (
            row.get("carry_answer"),
            row.get("shock_answer"),
            row.get("persistence_answer"),
        )
        if row.get("data_status") != "OK" or any(value in (None, "UNKNOWN") or pd.isna(value) for value in answers):
            event_status = "UNOBSERVABLE"
        elif (
            row["carry_answer"] == "SUPPORTIVE"
            and row["shock_answer"] == "CALM"
            and row["persistence_answer"] == "NORMAL"
        ):
            event_status = "ELIGIBLE"
        else:
            event_status = "NOT_APPLICABLE"
        record: dict[str, Any] = {
            "prediction_date": prediction_date,
            "event_status": event_status,
            "label": np.nan,
            "label_status": "CENSORED",
            "valid_through_session": pd.NaT,
            "outcome_available_at": pd.NaT,
            "positive_components": "",
        }
        if event_status == "NOT_APPLICABLE":
            record["label_status"] = "NOT_APPLICABLE"
            records.append(record)
            continue
        if event_status != "ELIGIBLE" or index + 5 >= len(daily):
            records.append(record)
            continue
        future = daily.iloc[index + 1 : index + 6].copy()
        fact_known = (
            future["hard_acute"].notna()
            & future["front_slope30"].notna()
            & future["broad_pressure_day"].notna()
            & future["carry_environment_state"].ne("UNKNOWN")
        )
        vintage_known = (
            future["hard_acute_formal_vintage_eligible"].fillna(False).astype(bool)
            & future["front_curve_formal_vintage_eligible"].fillna(False).astype(bool)
            & future["broad_pressure_day_formal_vintage_eligible"].fillna(False).astype(bool)
            & future["carry_environment_formal_vintage_eligible"].fillna(False).astype(bool)
        )
        if not bool((fact_known & vintage_known).all()):
            records.append(record)
            continue
        acute = future["hard_acute"].astype(bool)
        inverted = future["front_slope30"].lt(0)
        broad = future["broad_pressure_day"].astype(bool)
        closed = future["carry_environment_state"].eq("CLOSED")
        closed_pair = closed & closed.shift(1, fill_value=False)
        components: list[str] = []
        if acute.any():
            components.append("HARD_ACUTE")
        if inverted.any():
            components.append("FRONT_INVERSION")
        if broad.any():
            components.append("BROAD_PRESSURE")
        if closed_pair.any():
            components.append("CARRY_CLOSED_2")
        observed = bool(components)
        final_session = pd.Timestamp(future.iloc[-1]["session_date"]).normalize()
        record.update(
            {
                "label": int(observed),
                "label_status": "OBSERVED_1" if observed else "OBSERVED_0",
                "valid_through_session": final_session,
                "outcome_available_at": pd.Timestamp(decision_as_of(final_session)),
                "positive_components": ",".join(components),
            }
        )
        records.append(record)
    return pd.DataFrame(records)


def _overlap_cluster_ids(indices: Iterable[int], *, horizon: int) -> dict[int, int]:
    result: dict[int, int] = {}
    cluster = 0
    previous: int | None = None
    for index in sorted(int(value) for value in indices):
        if previous is None or index - previous > horizon:
            cluster += 1
        result[index] = cluster
        previous = index
    return result


def _univariate_split_diagnostic(frame: pd.DataFrame, feature: str) -> dict[str, Any]:
    direction = _feature_direction(frame, feature)
    development = frame.loc[frame["audit_window"].eq("DEVELOPMENT")].dropna(subset=[feature, "label"])
    confirmation = frame.loc[frame["audit_window"].eq("CONFIRMATION")].dropna(subset=[feature, "label"])
    result: dict[str, Any] = {"direction": direction}
    if (
        development.empty
        or confirmation.empty
        or development["label"].nunique() < 2
        or confirmation["label"].nunique() < 2
        or development[feature].nunique() < 2
    ):
        result["development_fit_confirmation_test"] = {"status": "INSUFFICIENT_EVIDENCE"}
        return result
    mean = float(development[feature].mean())
    scale = float(development[feature].std(ddof=0))
    if not math.isfinite(scale) or scale == 0:
        result["development_fit_confirmation_test"] = {"status": "CONSTANT_FEATURE"}
        return result
    model = make_logistic()
    x_development = ((development[[feature]] - mean) / scale).to_numpy(dtype=float)
    x_confirmation = ((confirmation[[feature]] - mean) / scale).to_numpy(dtype=float)
    model.fit(x_development, development["label"].to_numpy(dtype=int))
    probability = model.predict_proba(x_confirmation)[:, 1]
    labels = confirmation["label"].to_numpy(dtype=float)
    base_rate = float((development["label"].sum() + 1) / (len(development) + 2))
    model_brier = float(np.mean((probability - labels) ** 2))
    base_brier = float(np.mean((base_rate - labels) ** 2))
    result["development_fit_confirmation_test"] = {
        "status": "HISTORICAL_PARTITION_DIAGNOSTIC",
        "development_samples": int(len(development)),
        "confirmation_samples": int(len(confirmation)),
        "coefficient": float(model.coef_[0, 0]),
        "brier_model": model_brier,
        "brier_base": base_brier,
        "brier_skill": float(1.0 - model_brier / base_brier) if base_brier > 0 else None,
        "auc": float(roc_auc_score(labels, probability)),
    }
    return result


def _cohort_counts(frame: pd.DataFrame) -> dict[str, Any]:
    records: dict[str, Any] = {}
    for window, group in frame.groupby("audit_window"):
        records[str(window)] = {
            "completed": int(len(group)),
            "positive": int(group["label"].sum()),
            "negative": int(len(group) - group["label"].sum()),
            "base_rate": _finite(group["label"].mean()),
        }
    return records


def _fragility_audit(
    daily: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    ledger = _fragility_target_ledger(daily)
    ledger = ledger.rename(
        columns={column: f"calm_carry_breaks_5d__{column}" for column in ledger.columns if column != "prediction_date"}
    ).rename(columns={"prediction_date": "session_date"})
    result = daily.merge(ledger, on="session_date", how="left", validate="one_to_one")
    label_column = "calm_carry_breaks_5d__label"
    status_column = "calm_carry_breaks_5d__label_status"
    completed = result.loc[result[status_column].isin(["OBSERVED_0", "OBSERVED_1"])].copy()
    completed["label"] = completed[label_column].astype(float)
    completed["prediction_date"] = completed["session_date"]
    positive_indices = completed.index[completed["label"].eq(1)]
    cluster_map = _overlap_cluster_ids(positive_indices, horizon=5)
    result["calm_carry_breaks_5d__positive_cluster_id"] = pd.Series(cluster_map, dtype="Int64")
    completed["positive_cluster_id"] = completed.index.map(cluster_map)

    predictor_columns = (
        "d1_log_vvix",
        "d5_log_vvix",
        "vvix_close",
        "vvix_vix_coupling_residual",
        "tail_price_score",
        "skew_close",
        "d5_skew",
        "vrp_ewma94",
        "spx_5d_log_momentum",
        "near_stress_log_ratio",
        "d5_near_stress",
        "negative_front_slope30",
        "negative_d5_front_slope30",
        "negative_basis30_eod",
    )
    predictors = {feature: _univariate_split_diagnostic(completed, feature) for feature in predictor_columns}
    compensation = {
        str(window): {
            str(value): {
                "samples": int(len(group)),
                "event_rate": _finite(group["label"].mean()),
            }
            for value, group in window_group.groupby("carry_compensation")
        }
        for window, window_group in completed.groupby("audit_window")
    }

    duplication: dict[str, Any] = {}
    eligible = result["calm_carry_breaks_5d__event_status"].eq("ELIGIBLE")
    maximum_agreement = 0.0
    for event in (
        "acute_front_stress_5d",
        "front_inversion_5d",
        "broad_stress_persists_10d",
        "carry_environment_recovers_10d",
    ):
        other_label = f"{event}__label"
        other_status = f"{event}__label_status"
        common = result.loc[
            result[status_column].isin(["OBSERVED_0", "OBSERVED_1"])
            & result[other_status].isin(["OBSERVED_0", "OBSERVED_1"])
        ]
        agreement = float(common[label_column].eq(common[other_label]).mean()) if not common.empty else None
        if agreement is not None:
            maximum_agreement = max(maximum_agreement, agreement)
        duplication[event] = {
            "same_day_eligibility_overlap": int((eligible & result[f"{event}__event_status"].eq("ELIGIBLE")).sum()),
            "common_completed_labels": int(len(common)),
            "exact_label_agreement": agreement,
            "common_positive": int((common[label_column].eq(1) & common[other_label].eq(1)).sum()),
        }

    overall_positive = int(completed["label"].sum())
    overall_negative = int(len(completed) - overall_positive)
    positive_clusters = len(set(cluster_map.values()))
    sample_gate = bool(len(completed) >= 252 and overall_positive >= 20 and overall_negative >= 20)
    independence_gate = bool(positive_clusters >= 20 and maximum_agreement < 0.95)
    stable_incremental = []
    for feature, evidence in predictors.items():
        fit = evidence.get("development_fit_confirmation_test", {})
        if (
            evidence["direction"].get("two_window_direction_stable")
            and fit.get("status") == "HISTORICAL_PARTITION_DIAGNOSTIC"
            and float(fit.get("brier_skill", -math.inf)) > 0
        ):
            stable_incremental.append(feature)
    direction_gate = bool(stable_incremental)
    disposition = (
        "ACCEPTED_FOR_STAGE_B_SPEC_FREEZE" if sample_gate and independence_gate and direction_gate else "REJECTED"
    )
    summary = {
        "event_id": "calm_carry_breaks_5d",
        "future_predicate_weather_only": True,
        "product_inputs_used": False,
        "eligibility": {
            str(key): int(value) for key, value in result["calm_carry_breaks_5d__event_status"].value_counts().items()
        },
        "labels": {str(key): int(value) for key, value in result[status_column].value_counts().items()},
        "cohorts": _cohort_counts(completed),
        "completed": int(len(completed)),
        "positive": overall_positive,
        "negative": overall_negative,
        "positive_overlapping_window_clusters": positive_clusters,
        "positive_component_counts": {
            component: int(
                result["calm_carry_breaks_5d__positive_components"]
                .fillna("")
                .str.contains(component, regex=False)
                .sum()
            )
            for component in (
                "HARD_ACUTE",
                "FRONT_INVERSION",
                "BROAD_PRESSURE",
                "CARRY_CLOSED_2",
            )
        },
        "duplication": duplication,
        "maximum_exact_label_agreement": maximum_agreement,
        "predictor_diagnostics": predictors,
        "carry_compensation_event_rates": compensation,
        "stable_positive_confirmation_increment_predictors": stable_incremental,
        "gates": {
            "sample_and_20_20_class_gate": sample_gate,
            "independent_cluster_and_not_duplicate_gate": independence_gate,
            "two_window_direction_and_increment_gate": direction_gate,
        },
        "audit_disposition": disposition,
        "evidence_status": "HISTORICAL_REUSE_NOT_UNTOUCHED_CONFIRMATION",
    }
    return result, summary


def _phase_runs(phases: pd.Series) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    if phases.empty:
        return runs
    start = 0
    current = str(phases.iloc[0])
    for index in range(1, len(phases)):
        value = str(phases.iloc[index])
        if value == current:
            continue
        runs.append({"phase": current, "start": start, "end": index - 1})
        start = index
        current = value
    runs.append({"phase": current, "start": start, "end": len(phases) - 1})
    return runs


def _boundary_distance(row: pd.Series) -> float | None:
    distances: list[float] = []
    for column, thresholds in {
        "shock_score": (40.0, 65.0, 85.0),
        "tail_price_score": (60.0, 75.0, 90.0),
        "front_slope30": (0.0,),
        "basis30_eod": (0.0,),
        "near_stress_log_ratio": (0.0,),
    }.items():
        value = row.get(column)
        if value is not None and not pd.isna(value):
            distances.extend(abs(float(value) - threshold) for threshold in thresholds)
    return min(distances) if distances else None


def _micro_churn_audit(daily: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    result = daily.copy()
    result["micro_churn_id"] = pd.Series(pd.NA, index=result.index, dtype="Int64")
    result["micro_churn_class"] = pd.Series(pd.NA, index=result.index, dtype="object")
    raw_events = pd.DataFrame(
        {
            "hard_acute": result["hard_acute"].astype("boolean"),
            "front_inversion": result["front_slope30"].lt(0).astype("boolean"),
            "mid_pressure": result["mid_curve_pressure_state"].isin(["RISING", "PRICED"]).astype("boolean"),
            "broad_pressure": result["broad_pressure_day"].astype("boolean"),
            "carry_closed": result["carry_environment_state"].isin(["CLOSED", "RECOVERING"]).astype("boolean"),
        }
    )
    runs = _phase_runs(result["phase"])
    records: list[dict[str, Any]] = []
    answer_columns = (
        "carry_answer",
        "shock_answer",
        "tail_answer",
        "persistence_answer",
        "repair_answer",
    )
    for first, middle, last in zip(runs, runs[1:], runs[2:], strict=False):
        if first["phase"] != last["phase"] or first["phase"] == middle["phase"]:
            continue
        start = int(middle["start"]) - 1
        end = int(last["start"])
        if end - start > 3:
            continue
        interval = result.iloc[start : end + 1]
        if interval["data_status"].ne("OK").any() or interval["phase"].eq("UNKNOWN").any():
            continue
        boundary = raw_events.iloc[start : end + 1]
        if any(boundary[column].nunique(dropna=False) > 1 for column in boundary):
            continue
        endpoint_left = result.iloc[start]
        endpoint_right = result.iloc[end]
        if any(endpoint_left[column] != endpoint_right[column] for column in answer_columns):
            continue
        changed_answers = sorted(
            {
                column
                for column in answer_columns
                if result.iloc[int(middle["start"]) : int(middle["end"]) + 1][column].ne(endpoint_left[column]).any()
            }
        )
        fragility_changed = bool(interval["calm_carry_breaks_5d__event_status"].nunique(dropna=False) > 1)
        changed_probability_events = [
            event for event in EVENT_ORDER if interval[f"{event}__event_status"].nunique(dropna=False) > 1
        ]
        rank_change = PHASE_RISK_RANK.get(str(middle["phase"]), 3) - PHASE_RISK_RANK.get(str(first["phase"]), 3)
        churn_class = "RISK_OFF" if rank_change > 0 else "RISK_ON" if rank_change < 0 else "LATERAL"
        churn_id = len(records) + 1
        result.loc[int(middle["start"]) : int(middle["end"]), "micro_churn_id"] = churn_id
        result.loc[int(middle["start"]) : int(middle["end"]), "micro_churn_class"] = churn_class
        middle_rows = result.iloc[int(middle["start"]) : int(middle["end"]) + 1]
        records.append(
            {
                "micro_churn_id": churn_id,
                "phase_a": first["phase"],
                "phase_b": middle["phase"],
                "start_session": _date_text(result.iloc[start]["session_date"]),
                "return_session": _date_text(result.iloc[end]["session_date"]),
                "formal_session_span": end - start,
                "middle_sessions": int(len(middle_rows)),
                "class": churn_class,
                "changed_stable_answers": changed_answers,
                "fragility_eligibility_changed": fragility_changed,
                "probability_event_status_changed": changed_probability_events,
                "minimum_boundary_distance": _finite(
                    min(
                        value
                        for value in (_boundary_distance(row) for _, row in middle_rows.iterrows())
                        if value is not None
                    )
                ),
            }
        )
    classes = {name: sum(record["class"] == name for record in records) for name in ("RISK_OFF", "RISK_ON", "LATERAL")}
    pairs: dict[str, int] = {}
    for record in records:
        key = f"{record['phase_a']}->{record['phase_b']}->{record['phase_a']}"
        pairs[key] = pairs.get(key, 0) + 1
    permitted = [int(record["micro_churn_id"]) for record in records if record["class"] in {"RISK_ON", "LATERAL"}]
    summary = {
        "definition_replayed": True,
        "all_phase_transitions": int(result["phase"].ne(result["phase"].shift()).sum() - 1),
        "micro_churn_count": len(records),
        "classes": classes,
        "phase_pairs": pairs,
        "records": records,
        "repair_permitted_candidate_ids": permitted,
        "risk_off_repair_prohibited_ids": [
            int(record["micro_churn_id"]) for record in records if record["class"] == "RISK_OFF"
        ],
        "suppression_impact_for_permitted_candidates": {
            "raw_weather_event_delays": 0,
            "raw_weather_events_missed": 0,
            "continued_closed_sessions": int(
                sum(record["middle_sessions"] for record in records if record["class"] == "RISK_ON")
            ),
        },
        "frozen_economic_summary_only": {
            "economic_interval_phase_changes": 507,
            "actual_asset_switches": 241,
            "phase_changes_without_trade": 278,
            "date_level_intersection": "NOT_COMPUTED_CONTRACT_PROHIBITS_PRICE_LEDGER_READ",
        },
        "audit_disposition": (
            "OPEN_STATE_CHURN_002_LIMITED_TO_NUMBERED_RISK_ON_OR_LATERAL" if permitted else "REJECT_STATE_CHURN_002"
        ),
    }
    return result, summary


def _advanced_data_audit(daily: pd.DataFrame) -> dict[str, Any]:
    directly_derivable = {
        "d1_log_vvix": "d1_log_vvix" in daily,
        "spx_5d_log_momentum": "spx_5d_log_momentum" in daily,
        "vix9d_vix_convergence": "vix9d_vix_convergence_5d" in daily,
        "causal_vvix_vix_coupling_residual": "vvix_vix_coupling_residual" in daily,
        "ewma94_vrp_proxy": "vrp_ewma94" in daily,
    }
    unavailable = {
        "SKEW_1M_3M_6M_TERM_STRUCTURE": {
            "missing": "matched tenor series",
            "source_candidate": "authorized Cboe tenor history",
            "pit_requirement": "release timestamp and revisions",
        },
        "PARKINSON_RV": {
            "missing": "SPX high and low",
            "source_candidate": "authorized SPX OHLC",
            "pit_requirement": "session-complete OHLC available_at",
        },
        "GARMAN_KLASS_RV": {
            "missing": "SPX open high low close",
            "source_candidate": "authorized SPX OHLC",
            "pit_requirement": "session-complete OHLC available_at",
        },
        "MATCHED_HORIZON_VRP_SURFACE": {
            "missing": "matched IV and RV horizons",
            "source_candidate": "option-chain data contract",
            "pit_requirement": "PIT quote, revision, expiry and forward matching",
        },
        "NEAR_VARIANCE_SWAP_OR_OPTION_SURFACE": {
            "missing": "SPX option chain",
            "source_candidate": "licensed chain source",
            "pit_requirement": "PIT quotes, expiries, rates and rights",
        },
    }
    return {
        "directly_derivable_from_current_formal_data": directly_derivable,
        "all_current_derivations_available": all(directly_derivable.values()),
        "unavailable_without_new_contract": unavailable,
        "downloaded_purchased_or_imported": False,
        "data_option_002": "DEFERRED_NOT_P0",
    }


def _merge_candidate_oof(daily: pd.DataFrame, event: str, candidate: pd.DataFrame) -> pd.DataFrame:
    columns = ["prediction_date", "base_probability", "rolling_intercept_probability", "rolling_intercept_method"]
    selected = candidate[columns].rename(
        columns={
            "prediction_date": "session_date",
            **{column: f"{event}__duration_candidate__{column}" for column in columns if column != "prediction_date"},
        }
    )
    return daily.merge(selected, on="session_date", how="left", validate="one_to_one")


def _formal_candidate_pass(model_summary: dict[str, Any], key: str) -> bool:
    metrics = model_summary["latest_252"][key]
    return bool(
        metrics.get("samples") == 252
        and int(metrics.get("positives", 0)) >= 20
        and int(metrics.get("negatives", 0)) >= 20
        and float(metrics.get("brier_skill", -math.inf)) >= 0.02
        and float(metrics.get("ece", math.inf)) <= 0.07
    )


def run_v3_business_audit(project_dir: str | Path) -> dict[str, Path]:
    """Run the contract-frozen, price-blind MatVIX V3 Stage-A audit."""

    root = Path(project_dir).resolve()
    baseline_dir = root / "outputs" / "v3_baseline"
    manifest_path = baseline_dir / "v2_manifest.json"
    manifest = read_json(manifest_path)
    if manifest.get("v2_code_sha") != "a2a8a584f6435d7ffc972eb57b0928eeb0e4a802":
        raise ValueError("Frozen V2 baseline code SHA does not match the V3 contract")
    frozen_paths = {"features": baseline_dir / "v2_features.parquet", "states": baseline_dir / "v2_states.parquet", "targets": baseline_dir / "v2_targets.parquet", "oof": baseline_dir / "v2_oof.parquet", "station_summary": baseline_dir / "v2_station_summary.json"}
    for name, path in frozen_paths.items():
        entry = manifest["station_summary"] if name == "station_summary" else manifest["tables"][name]
        if _sha256(path) != entry["sha256"]:
            raise ValueError(f"Frozen V2 baseline hash mismatch: {name}")

    states = read_parquet(frozen_paths["states"])
    targets = read_parquet(frozen_paths["targets"])
    oof = read_parquet(frozen_paths["oof"])
    for frame, column in (
        (states, "session_date"),
        (targets, "prediction_date"),
        (oof, "prediction_date"),
    ):
        frame[column] = pd.to_datetime(frame[column]).dt.normalize()

    daily = _prepare_daily_facts(states, targets)
    daily, calibration, replayed = _calibration_audit(daily, targets, oof)
    carry, carry_candidate = _carry_audit(daily, targets, replayed["carry_environment_recovers_10d"])
    broad, broad_candidate = _broad_audit(
        daily,
        targets,
        replayed["broad_stress_persists_10d"],
        calibration,
    )
    daily = _merge_candidate_oof(daily, "carry_environment_recovers_10d", carry_candidate)
    daily = _merge_candidate_oof(daily, "broad_stress_persists_10d", broad_candidate)
    daily, fragility = _fragility_audit(daily)
    daily, micro_churn = _micro_churn_audit(daily)
    advanced_data = _advanced_data_audit(daily)

    calibration_replay_pass = all(
        event["free_platt_arithmetic"]["maximum_absolute_error"] is not None
        and float(event["free_platt_arithmetic"]["maximum_absolute_error"]) <= 1e-12
        and int(event["free_platt_arithmetic"]["calibration_sample_count_mismatches"]) == 0
        for event in calibration["events"].values()
    )
    duration_replay_pass = all(
        evidence["fixed_model_comparison" if name == "carry" else "fixed_direct_10d_model_comparison"]
        ["pit_integrity"][key] == 0
        for name, evidence in (("carry", carry), ("broad", broad))
        for key in ("purge_boundary_violations", "outcome_availability_violations")
    )
    carry_direct_pass = _formal_candidate_pass(carry["fixed_model_comparison"], "candidate_rolling_intercept")
    broad_direct_pass = _formal_candidate_pass(broad["fixed_direct_10d_model_comparison"], "candidate_rolling_intercept")
    stop_conditions = {
        "calibration_or_duration_not_pit_replayable": not (calibration_replay_pass and duration_replay_pass),
        "broad_actual_252_or_direct_skill_insufficient": not broad_direct_pass,
        "fragility_sample_independence_or_two_window_direction_insufficient": fragility["audit_disposition"] == "REJECTED",
        "new_unauthorized_data_required": False,
    }
    stop_triggered = any(stop_conditions.values())
    summary: dict[str, Any] = {
        "audit_version": AUDIT_VERSION,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "contract": "MATVIX_V3_CONSTRUCTION_PLAN.md v1.0",
        "baseline": {
            "v2_code_sha": manifest["v2_code_sha"],
            "manifest_sha256": _sha256(manifest_path),
            "sessions": int(len(daily)),
            "first_session": _date_text(daily["session_date"].min()),
            "last_session": _date_text(daily["session_date"].max()),
        },
        "evidence_boundary": {
            "weather_inputs_only": True,
            "product_prices_read": False,
            "economic_probe_content_read": False,
            "strategy_or_pnl_built": False,
            "html_generated": False,
            "quarantine_read": False,
            "threshold_model_window_or_feature_scan": False,
            "historical_pit_boundary": "ASSUMED_PIT",
            "confirmation_window_status": "HISTORICAL_REUSE_NOT_UNTOUCHED",
        },
        "calibration": calibration,
        "carry_duration_conditioned_10d": carry,
        "broad_direct_10d": broad,
        "calm_carry_breaks_5d": fragility,
        "micro_churn": micro_churn,
        "advanced_data_feasibility": advanced_data,
        "stage_a_gates": {
            "calibration_replay_pass": calibration_replay_pass,
            "duration_candidate_pit_replay_pass": duration_replay_pass,
            "carry_fixed_duration_candidate_historical_gate": carry_direct_pass,
            "broad_fixed_duration_candidate_historical_gate": broad_direct_pass,
            "fragility_audit_disposition": fragility["audit_disposition"],
        },
        "contract_stop_conditions": stop_conditions,
        "stop_triggered": stop_triggered,
        "next_action": (
            "STOP_AND_RECORD_EXACT_EVIDENCE" if stop_triggered else "FREEZE_STAGE_B_SEMANTICS_BEFORE_CODE_CHANGES"
        ),
    }
    output_dir = root / "outputs" / "v3_audit"
    daily_path = write_parquet(daily, output_dir / "business_audit_daily.parquet")
    summary_path = write_json(summary, output_dir / "business_audit_summary.json")
    return {"daily": daily_path, "summary": summary_path}
