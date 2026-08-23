from __future__ import annotations

import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any

import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression

from matvix.calendar import add_sessions, decision_as_of
from matvix.constants import BASE_RATE_ONLY_EVENTS, LOGISTIC_FEATURES
from matvix.probability.baseline import beta_smoothed_base_rate
from matvix.probability.calibration import acceptance_metrics, apply_intercept, fit_intercept


@dataclass(frozen=True)
class ProbabilitySpec:
    base_rate_max: int = 756
    base_rate_min: int = 252
    training_max: int = 1500
    training_min: int = 252
    training_min_positive: int = 30
    training_min_negative: int = 30
    purge_sessions: int = 20
    calibration_max: int = 252
    calibration_min_positive: int = 20
    calibration_min_negative: int = 20
    acceptance_samples: int = 252


def runtime_contract_status() -> dict[str, str | bool]:
    actual = version("scikit-learn")
    return {
        "required": "1.7.2",
        "actual": actual,
        "compatible": actual == "1.7.2",
    }


def require_formal_runtime() -> None:
    status = runtime_contract_status()
    if not status["compatible"]:
        raise RuntimeError(
            f"Formal MatVIX probability requires scikit-learn==1.7.2; found {status['actual']}"
        )


def make_logistic() -> LogisticRegression:
    return LogisticRegression(
        penalty="l2",
        C=1.0,
        solver="lbfgs",
        fit_intercept=True,
        dual=False,
        class_weight=None,
        warm_start=False,
        tol=1e-8,
        max_iter=1500,
        random_state=0,
    )


def _completed_before(
    merged: pd.DataFrame, prediction_date: pd.Timestamp, *, purge_sessions: int | None = None
) -> pd.DataFrame:
    as_of = pd.Timestamp(decision_as_of(prediction_date)).tz_convert("UTC")
    eligible = merged.loc[
        merged["label_status"].isin(["OBSERVED_0", "OBSERVED_1"])
        & (pd.to_datetime(merged["outcome_available_at"], utc=True) <= as_of)
        & (pd.to_datetime(merged["prediction_date"]) < prediction_date)
    ]
    if purge_sessions is not None:
        cutoff = add_sessions(prediction_date, -purge_sessions)
        eligible = eligible.loc[pd.to_datetime(eligible["prediction_date"]) <= cutoff]
    return eligible.sort_values("prediction_date")


def _fit_model(
    training: pd.DataFrame,
    event: str,
    spec: ProbabilitySpec,
    *,
    feature_names: Sequence[str] | None = None,
) -> tuple[LogisticRegression | None, dict[str, Any]]:
    features = list(LOGISTIC_FEATURES[event] if feature_names is None else feature_names)
    sample = training.dropna(subset=[*features, "label"]).tail(spec.training_max)
    positives = int(sample["label"].sum())
    negatives = len(sample) - positives
    metadata: dict[str, Any] = {
        "training_samples": len(sample),
        "training_positive": positives,
        "training_negative": negatives,
        "converged": False,
    }
    if (
        len(sample) < spec.training_min
        or positives < spec.training_min_positive
        or negatives < spec.training_min_negative
    ):
        return None, metadata
    model = make_logistic()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        model.fit(sample[features].to_numpy(dtype=float), sample["label"].to_numpy(dtype=int))
    converged = not any(issubclass(item.category, ConvergenceWarning) for item in caught)
    metadata["converged"] = converged
    metadata["iterations"] = int(model.n_iter_[0])
    return (model if converged else None), metadata


def _base_rate(
    completed: pd.DataFrame, spec: ProbabilitySpec
) -> tuple[float | None, dict[str, int]]:
    rate, count, positives, negatives = beta_smoothed_base_rate(
        completed["label"],
        max_samples=spec.base_rate_max,
        minimum_samples=spec.base_rate_min,
    )
    return rate, {
        "base_rate_samples": count,
        "base_rate_positive": positives,
        "base_rate_negative": negatives,
    }


def build_oof_ledger(
    state_features: pd.DataFrame,
    target_ledger: pd.DataFrame,
    event: str,
    *,
    spec: ProbabilitySpec | None = None,
    feature_names: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Build the complete sequential OOF ledger for one event."""

    spec = spec or ProbabilitySpec()
    raw = _build_raw_oof_rows(
        state_features,
        target_ledger,
        event,
        spec=spec,
        feature_names=feature_names,
    )
    return _append_sequential_calibration(raw, start_index=0, spec=spec)


def _build_raw_oof_rows(
    state_features: pd.DataFrame,
    target_ledger: pd.DataFrame,
    event: str,
    *,
    spec: ProbabilitySpec,
    prediction_dates: pd.DatetimeIndex | None = None,
    feature_names: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Fit raw OOF predictions, optionally only for explicit prediction dates.

    Restricting the prediction loop is what makes a PIT-safe append incremental:
    training still sees the complete history available at each new date, while
    already-published OOF predictions are never refit.
    """

    features = list(LOGISTIC_FEATURES[event] if feature_names is None else feature_names)
    source = state_features[["session_date", *features]].rename(
        columns={"session_date": "prediction_date"}
    )
    target = target_ledger.loc[target_ledger["event_id"] == event].copy()
    merged = target.merge(source, on="prediction_date", how="left").sort_values("prediction_date")
    selected_dates = None
    if prediction_dates is not None:
        selected_dates = {
            pd.Timestamp(value).normalize() for value in pd.DatetimeIndex(prediction_dates)
        }
    records: list[dict[str, Any]] = []
    for _, row in merged.iterrows():
        # A real OOF prediction is defined by what was observable at prediction
        # time.  Its later outcome may remain censored; that must not erase the
        # prediction from the ledger.  Censored rows are simply ineligible for
        # future training, calibration fitting and validation metrics.
        if row["event_status"] != "ELIGIBLE":
            continue
        prediction_date = pd.Timestamp(row["prediction_date"]).normalize()
        if selected_dates is not None and prediction_date not in selected_dates:
            continue
        training = _completed_before(merged, prediction_date, purge_sessions=spec.purge_sessions)
        completed = _completed_before(merged, prediction_date, purge_sessions=None)
        base_rate, base_meta = _base_rate(completed, spec)
        if event in BASE_RATE_ONLY_EVENTS:
            if base_rate is None:
                continue
            model = None
            model_meta: dict[str, Any] = {
                "training_samples": 0,
                "training_positive": 0,
                "training_negative": 0,
                "converged": False,
            }
        else:
            model, model_meta = (
                _fit_model(training, event, spec)
                if feature_names is None
                else _fit_model(training, event, spec, feature_names=features)
            )
        if event not in BASE_RATE_ONLY_EVENTS and (
            model is None or row[features].isna().any()
        ):
            continue
        if event in BASE_RATE_ONLY_EVENTS:
            latest_training_prediction = pd.NaT
            latest_training_outcome = pd.NaT
            raw_probability = np.nan
        else:
            assert model is not None
            latest_training_prediction = pd.Timestamp(training["prediction_date"].max()).normalize()
            latest_training_outcome = pd.to_datetime(
                training["outcome_available_at"], utc=True
            ).max()
            x = row[features].to_numpy(dtype=float).reshape(1, -1)
            raw_probability = float(model.predict_proba(x)[0, 1])
        label_observed = row["label_status"] in ("OBSERVED_0", "OBSERVED_1")
        records.append(
            {
                "event_id": event,
                "prediction_date": prediction_date,
                "outcome_available_at": row["outcome_available_at"],
                "label": int(row["label"]) if label_observed else np.nan,
                "label_status": row["label_status"],
                "raw_probability": raw_probability,
                "base_rate_at_prediction": base_rate,
                # Persist the actual boundary used by this sequential fit so
                # purge and completed-outcome invariants are auditable from
                # the ledger itself, not merely inferred from implementation.
                "training_latest_prediction_date": latest_training_prediction,
                "training_latest_outcome_available_at": latest_training_outcome,
                **base_meta,
                **model_meta,
            }
        )
    return pd.DataFrame(records)


_CALIBRATION_COLUMNS = (
    "published_probability",
    "calibration_method",
    "calibration_samples",
    "calibration_positive",
    "calibration_negative",
    "intercept_b",
)


def _append_sequential_calibration(
    raw_oof: pd.DataFrame,
    *,
    start_index: int,
    spec: ProbabilitySpec,
) -> pd.DataFrame:
    """Calibrate rows from ``start_index`` without changing prior predictions."""

    if raw_oof.empty:
        return raw_oof.copy()
    oof = raw_oof.sort_values("prediction_date").reset_index(drop=True)

    if start_index < 0 or start_index > len(oof):
        raise ValueError("start_index is outside the OOF ledger")
    if start_index:
        missing = [column for column in _CALIBRATION_COLUMNS if column not in oof]
        if missing:
            raise ValueError(
                "Existing OOF ledger lacks sequential calibration columns: " + ", ".join(missing)
            )
    else:
        oof["published_probability"] = oof["raw_probability"]
        base_only = oof["raw_probability"].isna() & oof["base_rate_at_prediction"].notna()
        oof.loc[base_only, "published_probability"] = oof.loc[
            base_only, "base_rate_at_prediction"
        ]
        oof["calibration_method"] = "IDENTITY_WARMUP"
        oof.loc[base_only, "calibration_method"] = "NOT_APPLICABLE"
        oof["calibration_samples"] = 0
        oof["calibration_positive"] = 0
        oof["calibration_negative"] = 0
        oof["intercept_b"] = np.nan

    for index in range(start_index, len(oof)):
        row = oof.iloc[index]
        if pd.isna(row["raw_probability"]):
            oof.at[index, "published_probability"] = row["base_rate_at_prediction"]
            oof.at[index, "calibration_method"] = "NOT_APPLICABLE"
            oof.at[index, "calibration_samples"] = 0
            oof.at[index, "calibration_positive"] = 0
            oof.at[index, "calibration_negative"] = 0
            oof.at[index, "intercept_b"] = np.nan
            continue
        prediction_date = pd.Timestamp(row["prediction_date"])
        as_of = pd.Timestamp(decision_as_of(prediction_date)).tz_convert("UTC")
        prior = oof.iloc[:index].copy()
        if not prior.empty:
            prior = prior.loc[
                prior["label_status"].isin(["OBSERVED_0", "OBSERVED_1"])
                & (pd.to_datetime(prior["outcome_available_at"], utc=True) <= as_of)
            ].tail(spec.calibration_max)
        positives = int(prior["label"].sum()) if not prior.empty else 0
        negatives = len(prior) - positives
        oof.at[index, "calibration_samples"] = len(prior)
        oof.at[index, "calibration_positive"] = positives
        oof.at[index, "calibration_negative"] = negatives
        if (
            len(prior) < spec.calibration_min_positive + spec.calibration_min_negative
            or positives < spec.calibration_min_positive
            or negatives < spec.calibration_min_negative
        ):
            oof.at[index, "published_probability"] = row["raw_probability"]
            oof.at[index, "calibration_method"] = "IDENTITY_WARMUP"
            oof.at[index, "intercept_b"] = np.nan
            continue
        intercept = fit_intercept(prior["raw_probability"].to_numpy(), prior["label"].to_numpy())
        oof.at[index, "published_probability"] = apply_intercept(
            float(row["raw_probability"]), intercept
        )
        oof.at[index, "calibration_method"] = "ROLLING_INTERCEPT_252"
        oof.at[index, "intercept_b"] = intercept
    return oof


def extend_oof_ledger(
    state_features: pd.DataFrame,
    target_ledger: pd.DataFrame,
    event: str,
    existing_oof: pd.DataFrame,
    new_prediction_dates: pd.DatetimeIndex,
    *,
    spec: ProbabilitySpec | None = None,
) -> pd.DataFrame:
    """Refresh outcomes and append only genuinely new sequential predictions.

    The raw and published probability fields on existing rows are immutable.
    Labels can move from ``CENSORED`` to observed when a newly appended state
    closes their complete outcome horizon.
    """

    spec = spec or ProbabilitySpec()
    existing = existing_oof.copy()
    if not existing.empty:
        target = target_ledger.loc[
            target_ledger["event_id"].eq(event),
            ["prediction_date", "outcome_available_at", "label", "label_status"],
        ].copy()
        target["prediction_date"] = pd.to_datetime(target["prediction_date"]).dt.normalize()
        target = target.set_index("prediction_date")
        existing["prediction_date"] = pd.to_datetime(existing["prediction_date"]).dt.normalize()
        missing_dates = ~existing["prediction_date"].isin(target.index)
        if missing_dates.any():
            raise ValueError(f"Cached OOF rows are absent from refreshed target ledger: {event}")
        for column in ("outcome_available_at", "label", "label_status"):
            existing[column] = existing["prediction_date"].map(target[column])

    appended = _build_raw_oof_rows(
        state_features,
        target_ledger,
        event,
        spec=spec,
        prediction_dates=new_prediction_dates,
    )
    if appended.empty:
        return existing.sort_values("prediction_date").reset_index(drop=True)

    if not existing.empty:
        if (
            pd.to_datetime(appended["prediction_date"]).min()
            <= pd.to_datetime(existing["prediction_date"]).max()
        ):
            raise ValueError("Incremental OOF dates must follow every cached prediction date")
        duplicate = set(pd.to_datetime(existing["prediction_date"]).dt.normalize()).intersection(
            pd.to_datetime(appended["prediction_date"]).dt.normalize()
        )
        if duplicate:
            dates = ", ".join(sorted(value.date().isoformat() for value in duplicate))
            raise ValueError(f"Incremental OOF append would duplicate prediction dates: {dates}")
        for column in _CALIBRATION_COLUMNS:
            if column in {
                "calibration_samples",
                "calibration_positive",
                "calibration_negative",
            }:
                appended[column] = 0
            elif column == "calibration_method":
                appended[column] = "IDENTITY_WARMUP"
            else:
                appended[column] = np.nan
        combined = pd.concat([existing, appended], ignore_index=True, sort=False)
    else:
        combined = appended

    combined = combined.sort_values("prediction_date").reset_index(drop=True)
    start_index = len(existing)
    return _append_sequential_calibration(combined, start_index=start_index, spec=spec)


def validation_as_of(
    oof: pd.DataFrame, prediction_date: pd.Timestamp, spec: ProbabilitySpec
) -> dict[str, Any]:
    if oof.empty:
        return {"accepted": False, "samples": 0}
    as_of = pd.Timestamp(decision_as_of(prediction_date)).tz_convert("UTC")
    completed = oof.loc[
        oof["published_probability"].notna()
        & oof["base_rate_at_prediction"].notna()
        & (pd.to_datetime(oof["outcome_available_at"], utc=True) <= as_of)
        & (pd.to_datetime(oof["prediction_date"]) < prediction_date)
    ].sort_values("prediction_date")
    # acceptance_metrics is frozen at 252 by the authority. Test overrides only
    # affect warmup, not the formal validation formula.
    return acceptance_metrics(completed)


def train_current_model(
    state_features: pd.DataFrame,
    target_ledger: pd.DataFrame,
    event: str,
    prediction_date: pd.Timestamp,
    *,
    spec: ProbabilitySpec | None = None,
) -> tuple[LogisticRegression | None, dict[str, Any], float | None, dict[str, int]]:
    spec = spec or ProbabilitySpec()
    features = LOGISTIC_FEATURES[event]
    source = state_features[["session_date", *features]].rename(
        columns={"session_date": "prediction_date"}
    )
    target = target_ledger.loc[target_ledger["event_id"] == event].copy()
    merged = target.merge(source, on="prediction_date", how="left").sort_values("prediction_date")
    training = _completed_before(merged, prediction_date, purge_sessions=spec.purge_sessions)
    completed = _completed_before(merged, prediction_date, purge_sessions=None)
    rate, base_meta = _base_rate(completed, spec)
    if event in BASE_RATE_ONLY_EVENTS:
        model = None
        model_meta = {
            "training_samples": 0,
            "training_positive": 0,
            "training_negative": 0,
            "converged": False,
        }
    else:
        model, model_meta = _fit_model(training, event, spec)
    return model, model_meta, rate, base_meta
