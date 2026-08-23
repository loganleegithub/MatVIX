from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import numpy as np
import pandas as pd

from matvix.calendar import add_sessions, decision_as_of
from matvix.constants import (
    BASE_RATE_ONLY_EVENTS,
    EVENT_HORIZONS,
    EVENT_ORDER,
    LOGISTIC_FEATURES,
    PROBABILITY_VERSION,
)
from matvix.probability.calibration import apply_intercept, fit_intercept
from matvix.probability.targets import (
    add_carry_duration_facts,
    add_event_statuses,
    build_target_ledger,
)
from matvix.probability.walk_forward import (
    ProbabilitySpec,
    build_oof_ledger,
    extend_oof_ledger,
    runtime_contract_status,
    train_current_model,
    validation_as_of,
)

PROBABILITY_ARTIFACT_CONTRACT_VERSION = "2"

# Only fields that can alter event eligibility, outcome labels, model inputs or
# their chronological order belong in the probability history fingerprint.
# An unrelated dashboard-only field should not force thousands of OOF refits.
PROBABILITY_STATE_COLUMNS = tuple(
    dict.fromkeys(
        [
            "session_date",
            "data_status",
            "formal_vintage_eligible",
            "hard_acute",
            "front_slope30",
            "mid_curve_pressure_state",
            "broad_pressure_day",
            "carry_environment_state",
            "front_pressure",
            "hard_acute_formal_vintage_eligible",
            "front_curve_formal_vintage_eligible",
            "mid_curve_formal_vintage_eligible",
            "broad_pressure_day_formal_vintage_eligible",
            "carry_environment_formal_vintage_eligible",
            *(feature for event in EVENT_ORDER for feature in LOGISTIC_FEATURES[event]),
        ]
    )
)


class ProbabilityArtifactContractError(ValueError):
    """A persisted probability artifact cannot be trusted for this history."""


def _empty_event(
    event_status: str, interpretation: str, model_status: str = "NOT_RUN"
) -> dict[str, Any]:
    return {
        "event_status": event_status,
        "model_status": model_status,
        "probability_kind": None,
        "raw_probability": None,
        "probability": None,
        "base_rate": None,
        "uplift": None,
        "calibration_method": None,
        "calibration_samples": None,
        "calibration_positive": None,
        "calibration_negative": None,
        "intercept_b": None,
        "valid_through_session": None,
        "interpretation": interpretation,
    }


def _base_rate_event(base_rate: float, valid_through: str) -> dict[str, Any]:
    return {
        "event_status": "ELIGIBLE",
        "model_status": "BASE_RATE_ONLY",
        "probability_kind": "HISTORICAL_REFERENCE",
        "raw_probability": None,
        "probability": float(base_rate),
        "base_rate": float(base_rate),
        "uplift": 0.0,
        "calibration_method": "NOT_APPLICABLE",
        "calibration_samples": 0,
        "calibration_positive": 0,
        "calibration_negative": 0,
        "intercept_b": None,
        "valid_through_session": valid_through,
        "interpretation": "当前只使用同类历史发生率，特征模型未提供增量判断",
    }


def _conditional_event(
    raw_probability: float,
    probability: float,
    base_rate: float,
    valid_through: str,
    *,
    calibration_samples: int,
    calibration_positive: int,
    calibration_negative: int,
    intercept_b: float | None,
    warmup: bool = False,
) -> dict[str, Any]:
    uplift = float(probability - base_rate)
    if uplift >= 0.10:
        comparison = "明显高于历史基准"
    elif uplift > 0:
        comparison = "略高于历史基准"
    elif uplift == 0:
        comparison = "仅显示历史基准"
    else:
        comparison = "低于历史基准"
    return {
        "event_status": "ELIGIBLE",
        "model_status": "IDENTITY_WARMUP" if warmup else "CALIBRATED_MODEL",
        "probability_kind": "FEATURE_CONDITIONAL",
        "raw_probability": float(raw_probability),
        "probability": float(probability),
        "base_rate": float(base_rate),
        "uplift": uplift,
        "calibration_method": "IDENTITY_WARMUP" if warmup else "ROLLING_INTERCEPT_252",
        "calibration_samples": calibration_samples,
        "calibration_positive": calibration_positive,
        "calibration_negative": calibration_negative,
        "intercept_b": intercept_b,
        "valid_through_session": valid_through,
        "interpretation": (
            f"当前 {probability:.1%}，同类历史基准 {base_rate:.1%}，"
            f"相差 {uplift * 100:+.1f} 个百分点，{comparison}"
        ),
    }


def probability_for_event(
    state_features: pd.DataFrame,
    target_ledger: pd.DataFrame,
    event: str,
    prediction_date: pd.Timestamp,
    *,
    oof: pd.DataFrame | None = None,
    spec: ProbabilitySpec | None = None,
    formal_runtime_required: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], pd.DataFrame]:
    spec = spec or ProbabilitySpec()
    status_frame = add_event_statuses(state_features)
    current = status_frame.loc[
        pd.to_datetime(status_frame["session_date"]).dt.normalize() == prediction_date.normalize()
    ]
    if current.empty:
        return (
            _empty_event("UNOBSERVABLE", "当前输入不足，无法观察该问题"),
            {"reason": "prediction_date_missing"},
            pd.DataFrame(),
        )
    row = current.iloc[-1]
    current_status = str(row[f"{event}__event_status"])
    if current_status == "UNOBSERVABLE":
        return (
            _empty_event("UNOBSERVABLE", "当前输入不足，无法观察该问题"),
            {"reason": "event_unobservable"},
            pd.DataFrame(),
        )
    if current_status == "NOT_APPLICABLE":
        return (
            _empty_event("NOT_APPLICABLE", "当前状态已存在或该转移问题不适用"),
            {"reason": "event_not_applicable"},
            pd.DataFrame(),
        )

    horizon = EVENT_HORIZONS[event]
    valid_through = add_sessions(prediction_date, horizon).date().isoformat()
    model, model_meta, base_rate, base_meta = train_current_model(
        state_features, target_ledger, event, prediction_date, spec=spec
    )
    metadata: dict[str, Any] = {
        "event_id": event,
        "prediction_date": prediction_date.date().isoformat(),
        "probability_spec": asdict(spec),
        "runtime": runtime_contract_status(),
        **model_meta,
        **base_meta,
    }
    if base_rate is None:
        return (
            _empty_event(
                "ELIGIBLE",
                "正式历史样本不足，当前不发布概率",
                model_status="INSUFFICIENT_HISTORY",
            ),
            metadata,
            pd.DataFrame() if oof is None else oof,
        )

    if event in BASE_RATE_ONLY_EVENTS:
        metadata["publication_policy"] = "BASE_RATE_ONLY_EXEMPT"
        return _base_rate_event(base_rate, valid_through), metadata, (
            pd.DataFrame() if oof is None else oof
        )

    if oof is None:
        oof = build_oof_ledger(state_features, target_ledger, event, spec=spec)
    metadata["oof_rows"] = len(oof)
    runtime_ok = bool(runtime_contract_status()["compatible"])
    if formal_runtime_required and not runtime_ok:
        metadata["fallback_reason"] = "scikit_learn_version_mismatch"
        return _base_rate_event(base_rate, valid_through), metadata, oof
    if model is None:
        metadata["fallback_reason"] = "logistic_unavailable_or_not_converged"
        return _base_rate_event(base_rate, valid_through), metadata, oof

    features = LOGISTIC_FEATURES[event]
    x = row[features].to_numpy(dtype=float).reshape(1, -1)
    raw_probability = float(model.predict_proba(x)[0, 1])
    metadata["raw_probability"] = raw_probability

    prediction_as_of = pd.Timestamp(decision_as_of(prediction_date)).tz_convert("UTC")
    calibration = (
        oof.loc[
            (pd.to_datetime(oof["prediction_date"]) < prediction_date)
            & (pd.to_datetime(oof["outcome_available_at"], utc=True) <= prediction_as_of)
        ]
        .sort_values("prediction_date")
        .tail(spec.calibration_max)
    )
    positives = int(calibration["label"].sum()) if not calibration.empty else 0
    negatives = len(calibration) - positives
    metadata.update(
        {
            "calibration_samples": len(calibration),
            "calibration_positive": positives,
            "calibration_negative": negatives,
        }
    )
    if (
        len(calibration) < spec.calibration_min_positive + spec.calibration_min_negative
        or positives < spec.calibration_min_positive
        or negatives < spec.calibration_min_negative
    ):
        metadata["publication_method"] = "IDENTITY_WARMUP"
        return (
            _conditional_event(
                raw_probability,
                raw_probability,
                base_rate,
                valid_through,
                calibration_samples=len(calibration),
                calibration_positive=positives,
                calibration_negative=negatives,
                intercept_b=None,
                warmup=True,
            ),
            metadata,
            oof,
        )
    intercept = fit_intercept(
        calibration["raw_probability"].to_numpy(), calibration["label"].to_numpy()
    )
    probability = apply_intercept(raw_probability, intercept)
    metadata.update(
        {
            "intercept_b": intercept,
            "publication_method": "ROLLING_INTERCEPT_252",
            # Prospective 001 records the causally available shadow candidate
            # even when the frozen historical publication gate falls back to
            # BaseRate. This metadata never changes the published snapshot.
            "candidate_probability": probability,
        }
    )

    validation = validation_as_of(oof, prediction_date, spec)
    metadata["validation"] = validation
    if not bool(validation.get("accepted", False)):
        metadata["fallback_reason"] = "brier_or_ece_gate_not_met"
        return _base_rate_event(base_rate, valid_through), metadata, oof

    metadata["published_probability"] = probability
    return (
        _conditional_event(
            raw_probability,
            probability,
            base_rate,
            valid_through,
            calibration_samples=len(calibration),
            calibration_positive=positives,
            calibration_negative=negatives,
            intercept_b=intercept,
        ),
        metadata,
        oof,
    )


def outlook_answer(data_status: str, events: dict[str, dict[str, Any]]) -> str:
    if data_status != "OK":
        return "UNKNOWN"
    statuses = [events[event]["event_status"] for event in EVENT_ORDER]
    if "ELIGIBLE" not in statuses and "UNOBSERVABLE" in statuses:
        return "UNKNOWN"
    if all(status == "NOT_APPLICABLE" for status in statuses):
        return "NOT_APPLICABLE"
    conditional = [
        (event, events[event]["uplift"])
        for event in EVENT_ORDER
        if events[event]["event_status"] == "ELIGIBLE"
        and events[event]["model_status"] == "CALIBRATED_MODEL"
    ]
    if conditional:
        event, uplift = max(conditional, key=lambda item: (item[1], -EVENT_ORDER.index(item[0])))
        return event if float(uplift) >= 0.10 else "NO_STRONG_EDGE"
    if any(
        events[event]["event_status"] == "ELIGIBLE"
        and events[event]["model_status"] == "BASE_RATE_ONLY"
        for event in EVENT_ORDER
    ):
        return "BASE_RATE_ONLY"
    return "UNKNOWN"


def probability_availability_report(
    targets: pd.DataFrame, oof: pd.DataFrame
) -> dict[str, dict[str, Any]]:
    """Report the first date on which each probability layer became usable.

    Dates are derived from the actual target and OOF ledgers, never inferred
    from a planned sample size. ``base_rate`` is available when the 252nd
    completed eligible label's outcome is available; Logistic and rolling-intercept
    dates are the first sequential OOF rows actually produced.
    """

    report: dict[str, dict[str, Any]] = {}
    for event in EVENT_ORDER:
        event_targets = targets.loc[targets.get("event_id", pd.Series(dtype=str)).eq(event)].copy()
        completed = event_targets.loc[
            event_targets.get("label_status", pd.Series(dtype=str)).isin(
                ["OBSERVED_0", "OBSERVED_1"]
            )
        ].sort_values(["outcome_available_at", "prediction_date"])
        first_label = (
            pd.Timestamp(completed.iloc[0]["prediction_date"]).date().isoformat()
            if not completed.empty
            else None
        )
        base_rate_available = None
        if len(completed) >= 252:
            available = pd.to_datetime(completed.iloc[251]["outcome_available_at"], utc=True)
            base_rate_available = available.tz_convert("America/New_York").date().isoformat()

        if oof.empty or "event_id" not in oof:
            event_oof = pd.DataFrame()
        else:
            event_oof = oof.loc[oof["event_id"].eq(event)].sort_values("prediction_date")
        logistic_rows = (
            event_oof.loc[event_oof["raw_probability"].notna()]
            if not event_oof.empty and "raw_probability" in event_oof
            else pd.DataFrame()
        )
        logistic_available = (
            pd.Timestamp(logistic_rows.iloc[0]["prediction_date"]).date().isoformat()
            if not logistic_rows.empty
            else None
        )
        published_rows = (
            event_oof.loc[event_oof["calibration_method"].eq("ROLLING_INTERCEPT_252")]
            if not event_oof.empty and "calibration_method" in event_oof
            else pd.DataFrame()
        )
        published_available = (
            pd.Timestamp(published_rows.iloc[0]["prediction_date"]).date().isoformat()
            if not published_rows.empty
            else None
        )
        report[event] = {
            "first_completed_label_prediction_date": first_label,
            "base_rate_available_date": base_rate_available,
            "first_logistic_oof_prediction_date": logistic_available,
            "first_rolling_intercept_oof_prediction_date": published_available,
            "completed_eligible_samples": int(len(completed)),
            "positive_samples": int(completed["label"].sum()) if not completed.empty else 0,
            "negative_samples": int(len(completed) - completed["label"].sum())
            if not completed.empty
            else 0,
        }
    return report


def _normalize_state_history(state_features: pd.DataFrame) -> pd.DataFrame:
    if "session_date" not in state_features:
        raise ValueError("Probability history requires session_date")
    frame = state_features.copy()
    frame["session_date"] = pd.to_datetime(frame["session_date"]).dt.normalize()
    if frame["session_date"].isna().any():
        raise ValueError("Probability history contains an invalid session_date")
    frame = frame.sort_values("session_date", kind="stable").reset_index(drop=True)
    if frame["session_date"].duplicated().any():
        raise ValueError("Probability history must contain one row per session_date")
    return add_carry_duration_facts(frame)


def _canonical_digest_value(value: object) -> object:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        missing = False
    if isinstance(missing, (bool, np.bool_)) and bool(missing):
        return None
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return {"timestamp": pd.Timestamp(value).isoformat()}
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, float, np.integer, np.floating)):
        number = float(value)
        if np.isposinf(number):
            return {"number": "+inf"}
        if np.isneginf(number):
            return {"number": "-inf"}
        return {"number": format(number, ".17g")}
    return str(value)


def _stable_frame_digest(
    frame: pd.DataFrame,
    *,
    columns: tuple[str, ...] | None = None,
    order_by: tuple[str, ...] = (),
) -> str:
    selected_columns = list(columns) if columns is not None else sorted(frame.columns)
    canonical = frame.copy()
    for column in selected_columns:
        if column not in canonical:
            canonical[column] = None
    canonical = canonical[selected_columns]
    sort_columns = [column for column in order_by if column in canonical]
    if sort_columns and not canonical.empty:
        canonical = canonical.sort_values(sort_columns, kind="stable", na_position="last")
    canonical = canonical.reset_index(drop=True)

    digest = hashlib.sha256()
    digest.update(
        json.dumps(selected_columns, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    digest.update(b"\n")
    for row in canonical.itertuples(index=False, name=None):
        encoded = json.dumps(
            [_canonical_digest_value(value) for value in row],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        digest.update(encoded.encode("utf-8"))
        digest.update(b"\n")
    return "sha256:" + digest.hexdigest()


def probability_state_fingerprint(state_features: pd.DataFrame) -> dict[str, Any]:
    frame = _normalize_state_history(state_features)
    return {
        "row_count": int(len(frame)),
        "first_session_date": (
            frame.iloc[0]["session_date"].date().isoformat() if not frame.empty else None
        ),
        "last_session_date": (
            frame.iloc[-1]["session_date"].date().isoformat() if not frame.empty else None
        ),
        "relevant_columns": list(PROBABILITY_STATE_COLUMNS),
        "present_relevant_columns": [
            column for column in PROBABILITY_STATE_COLUMNS if column in frame.columns
        ],
        "relevant_columns_digest": _stable_frame_digest(
            frame,
            columns=PROBABILITY_STATE_COLUMNS,
            order_by=("session_date",),
        ),
    }


def probability_runtime_fingerprint() -> dict[str, str]:
    packages = ("numpy", "pandas", "scipy", "scikit-learn")
    result: dict[str, str] = {}
    for package in packages:
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = "MISSING"
    return result


def _artifact_fingerprint(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "row_count": int(len(frame)),
        "columns": sorted(frame.columns),
        "digest": _stable_frame_digest(
            frame,
            order_by=("event_id", "prediction_date"),
        ),
    }


def build_probability_artifact_contract(
    state_features: pd.DataFrame,
    target_ledger: pd.DataFrame,
    oof_ledger: pd.DataFrame,
    *,
    spec: ProbabilitySpec | None = None,
    formal_runtime_required: bool = True,
    build_mode: str = "FULL_REBUILD",
    previous_state_rows: int | None = None,
) -> dict[str, Any]:
    spec = spec or ProbabilitySpec()
    contract: dict[str, Any] = {
        "artifact_contract_version": PROBABILITY_ARTIFACT_CONTRACT_VERSION,
        "probability_version": PROBABILITY_VERSION,
        "probability_spec": asdict(spec),
        "runtime": probability_runtime_fingerprint(),
        "runtime_contract": runtime_contract_status(),
        "formal_runtime_required": bool(formal_runtime_required),
        "state_history": probability_state_fingerprint(state_features),
        "artifacts": {
            "target_ledger": _artifact_fingerprint(target_ledger),
            "oof_ledger": _artifact_fingerprint(oof_ledger),
        },
        "build_mode": build_mode,
    }
    if previous_state_rows is not None:
        contract["previous_state_rows"] = int(previous_state_rows)
    return contract


def validate_probability_artifact_contract(
    target_ledger: pd.DataFrame,
    oof_ledger: pd.DataFrame,
    contract: dict[str, Any],
    *,
    spec: ProbabilitySpec | None = None,
    formal_runtime_required: bool = True,
) -> None:
    """Reject any cached ledger without an exact, self-verifying contract."""

    spec = spec or ProbabilitySpec()
    expected = {
        "artifact_contract_version": PROBABILITY_ARTIFACT_CONTRACT_VERSION,
        "probability_version": PROBABILITY_VERSION,
        "probability_spec": asdict(spec),
        "runtime": probability_runtime_fingerprint(),
        "runtime_contract": runtime_contract_status(),
        "formal_runtime_required": bool(formal_runtime_required),
    }
    for key, value in expected.items():
        if contract.get(key) != value:
            raise ProbabilityArtifactContractError(f"probability cache {key} mismatch")

    history = contract.get("state_history")
    if not isinstance(history, dict):
        raise ProbabilityArtifactContractError("probability cache lacks state history digest")
    required_history = {
        "row_count",
        "first_session_date",
        "last_session_date",
        "relevant_columns",
        "present_relevant_columns",
        "relevant_columns_digest",
    }
    if not required_history.issubset(history):
        raise ProbabilityArtifactContractError("probability cache state history is incomplete")
    if history.get("relevant_columns") != list(PROBABILITY_STATE_COLUMNS):
        raise ProbabilityArtifactContractError("probability cache relevant columns mismatch")
    row_count = history.get("row_count")
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 0:
        raise ProbabilityArtifactContractError("probability cache state row count is invalid")

    required_targets = {
        "event_id",
        "prediction_date",
        "event_status",
        "label",
        "label_status",
        "outcome_available_at",
    }
    if not required_targets.issubset(target_ledger.columns):
        raise ProbabilityArtifactContractError("cached target ledger schema is incomplete")
    if not target_ledger.empty and target_ledger.duplicated(["event_id", "prediction_date"]).any():
        raise ProbabilityArtifactContractError("cached target ledger contains duplicate keys")
    if len(target_ledger) != row_count * len(EVENT_ORDER):
        raise ProbabilityArtifactContractError("cached target ledger is incomplete")
    if set(target_ledger["event_id"].dropna()) != set(EVENT_ORDER):
        raise ProbabilityArtifactContractError("cached target ledger event set mismatch")
    if not oof_ledger.empty:
        required_oof = {
            "event_id",
            "prediction_date",
            "raw_probability",
            "published_probability",
            "calibration_method",
            "calibration_samples",
            "calibration_positive",
            "calibration_negative",
            "intercept_b",
            "label",
            "label_status",
            "outcome_available_at",
            "training_latest_prediction_date",
            "training_latest_outcome_available_at",
        }
        if not required_oof.issubset(oof_ledger.columns):
            raise ProbabilityArtifactContractError("cached OOF ledger schema is incomplete")
        if oof_ledger.duplicated(["event_id", "prediction_date"]).any():
            raise ProbabilityArtifactContractError("cached OOF ledger contains duplicate keys")
        unknown_events = set(oof_ledger["event_id"].dropna()) - set(EVENT_ORDER)
        if unknown_events:
            raise ProbabilityArtifactContractError("cached OOF ledger contains unknown events")

    artifacts = contract.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ProbabilityArtifactContractError("probability cache lacks artifact digests")
    actual = {
        "target_ledger": _artifact_fingerprint(target_ledger),
        "oof_ledger": _artifact_fingerprint(oof_ledger),
    }
    for name, fingerprint in actual.items():
        if artifacts.get(name) != fingerprint:
            raise ProbabilityArtifactContractError(f"cached {name} digest mismatch")


def resolve_probability_artifacts(
    state_features: pd.DataFrame,
    *,
    cached_targets: pd.DataFrame | None = None,
    cached_oof: pd.DataFrame | None = None,
    cached_contract: dict[str, Any] | None = None,
    spec: ProbabilitySpec | None = None,
    formal_runtime_required: bool = True,
    force_full_rebuild: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], str]:
    """Resolve exact reuse, append-only extension, or a required full rebuild."""

    spec = spec or ProbabilitySpec()
    frame = _normalize_state_history(state_features)

    def full_build(action: str) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], str]:
        targets, oof = prepare_probability_artifacts(
            frame,
            spec=spec,
            formal_runtime_required=formal_runtime_required,
        )
        contract = build_probability_artifact_contract(
            frame,
            targets,
            oof,
            spec=spec,
            formal_runtime_required=formal_runtime_required,
            build_mode="FULL_REBUILD",
        )
        return targets, oof, contract, action

    if force_full_rebuild:
        return full_build("FULL_REBUILD_FORCED")
    if cached_targets is None or cached_oof is None or cached_contract is None:
        return full_build("FULL_REBUILD_MISSING_CACHE")

    try:
        validate_probability_artifact_contract(
            cached_targets,
            cached_oof,
            cached_contract,
            spec=spec,
            formal_runtime_required=formal_runtime_required,
        )
    except ProbabilityArtifactContractError:
        return full_build("FULL_REBUILD_INVALID_CACHE")

    prior_history = cached_contract["state_history"]
    prior_rows = int(prior_history["row_count"])
    current_rows = len(frame)
    if current_rows == prior_rows:
        current_fingerprint = probability_state_fingerprint(frame)
        if current_fingerprint == prior_history:
            return cached_targets, cached_oof, cached_contract, "EXACT_CACHE_HIT"
        return full_build("FULL_REBUILD_HISTORY_CHANGED")
    if current_rows < prior_rows:
        return full_build("FULL_REBUILD_HISTORY_TRUNCATED")

    prefix_fingerprint = probability_state_fingerprint(frame.iloc[:prior_rows])
    if prefix_fingerprint != prior_history:
        return full_build("FULL_REBUILD_HISTORY_CHANGED")

    targets = build_target_ledger(frame)
    runtime_ok = bool(runtime_contract_status()["compatible"])
    events_to_build = (
        BASE_RATE_ONLY_EVENTS
        if formal_runtime_required and not runtime_ok
        else EVENT_ORDER
    )
    new_dates = pd.DatetimeIndex(frame.iloc[prior_rows:]["session_date"])
    ledgers: list[pd.DataFrame] = []
    for event in events_to_build:
        event_oof = (
            cached_oof.loc[cached_oof["event_id"].eq(event)].copy()
            if not cached_oof.empty and "event_id" in cached_oof
            else pd.DataFrame()
        )
        ledger = extend_oof_ledger(
            frame,
            targets,
            event,
            event_oof,
            new_dates,
            spec=spec,
        )
        if not ledger.empty:
            ledgers.append(ledger)
    combined_oof = pd.concat(ledgers, ignore_index=True) if ledgers else pd.DataFrame()

    contract = build_probability_artifact_contract(
        frame,
        targets,
        combined_oof,
        spec=spec,
        formal_runtime_required=formal_runtime_required,
        build_mode="INCREMENTAL_APPEND",
        previous_state_rows=prior_rows,
    )
    return targets, combined_oof, contract, "INCREMENTAL_APPEND"


def prepare_probability_artifacts(
    state_features: pd.DataFrame,
    *,
    spec: ProbabilitySpec | None = None,
    formal_runtime_required: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build target and sequential OOF ledgers once for a complete history.

    A caller that emits many daily snapshots must reuse these ledgers.  They
    depend on the full PIT state history and the frozen probability spec, not
    on the individual snapshot date.
    """

    spec = spec or ProbabilitySpec()
    frame = _normalize_state_history(state_features)
    targets = build_target_ledger(frame)
    runtime_ok = bool(runtime_contract_status()["compatible"])
    events_to_build = (
        BASE_RATE_ONLY_EVENTS
        if formal_runtime_required and not runtime_ok
        else EVENT_ORDER
    )
    ledgers = [build_oof_ledger(frame, targets, event, spec=spec) for event in events_to_build]
    nonempty = [ledger for ledger in ledgers if not ledger.empty]
    combined = pd.concat(nonempty, ignore_index=True) if nonempty else pd.DataFrame()
    return targets, combined


def run_probability_job(
    state_features: pd.DataFrame,
    *,
    prediction_date: pd.Timestamp | str | None = None,
    spec: ProbabilitySpec | None = None,
    formal_runtime_required: bool = True,
    target_ledger: pd.DataFrame | None = None,
    oof_ledger: pd.DataFrame | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], pd.DataFrame, pd.DataFrame]:
    spec = spec or ProbabilitySpec()
    frame = _normalize_state_history(state_features)
    date = (
        frame["session_date"].max()
        if prediction_date is None
        else pd.Timestamp(prediction_date).normalize()
    )
    if (target_ledger is None) != (oof_ledger is None):
        raise ValueError("target_ledger and oof_ledger must be supplied together")
    if target_ledger is None:
        targets, combined_oof = prepare_probability_artifacts(
            frame,
            spec=spec,
            formal_runtime_required=formal_runtime_required,
        )
    else:
        targets = target_ledger
        combined_oof = oof_ledger
    events: dict[str, dict[str, Any]] = {}
    metadata: dict[str, Any] = {}
    for event in EVENT_ORDER:
        event_oof = (
            combined_oof.loc[combined_oof["event_id"].eq(event)].copy()
            if not combined_oof.empty and "event_id" in combined_oof
            else pd.DataFrame()
        )
        result, event_metadata, _ = probability_for_event(
            frame,
            targets,
            event,
            date,
            oof=event_oof,
            spec=spec,
            formal_runtime_required=formal_runtime_required,
        )
        events[event] = result
        metadata[event] = event_metadata
    metadata["availability"] = probability_availability_report(targets, combined_oof)
    return events, metadata, targets, combined_oof
