from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from matvix.calendar import add_sessions, decision_as_of
from matvix.constants import (
    EVENT_HORIZONS,
    EVENT_ORDER,
    LOGISTIC_FEATURES,
)
from matvix.output import validate_daily_output
from matvix.probability.baseline import beta_smoothed_base_rate
from matvix.probability.calibration import acceptance_metrics, apply_platt
from matvix.probability.engine import outlook_answer, probability_for_event
from matvix.probability.targets import add_event_statuses
from matvix.probability.walk_forward import ProbabilitySpec, runtime_contract_status
from matvix.source_identity import OFFICIAL_OBSERVATION_IDENTITIES, VX_SETTLE_IDENTITY
from matvix.storage import write_json

REQUIRED_SERIES = (
    "VIX_OPEN",
    "VIX_HIGH",
    "VIX_LOW",
    "VIX_CLOSE",
    "VIX9D_CLOSE",
    "VIX3M_CLOSE",
    "VIX6M_CLOSE",
    "VVIX_CLOSE",
    "SKEW_CLOSE",
    "SPX_CLOSE",
)
SCORE_COLUMNS = (
    "carry_risk_score",
    "shock_score",
    "tail_price_score",
    "persistence_score",
    "repair_score",
    "baseline_score",
)
ANSWER_COLUMNS = (
    "carry_answer",
    "shock_answer",
    "tail_answer",
    "persistence_answer",
    "repair_answer",
)
ANSWER_VALUES = {
    "carry_answer": {"SUPPORTIVE", "MIXED", "STRESSED", "INVERTED"},
    "shock_answer": {"CALM", "BUILDING", "HIGH", "ACUTE"},
    "tail_answer": {"NORMAL", "ELEVATED", "RICH", "EXTREME"},
    "persistence_answer": {
        "NORMAL",
        "FRONT_LOCALIZED",
        "DIFFUSING",
        "PERSISTENT",
        "MIXED",
    },
    "repair_answer": {"INACTIVE", "BUILDING", "CONFIRMED"},
}
PHASE_VALUES = {
    "ACUTE_FRONT_STRESS",
    "REPAIR_IN_PROGRESS",
    "BROAD_PERSISTENT_STRESS",
    "PRESSURE_DIFFUSING",
    "FRONT_LOCALIZED_STRESS",
    "TAIL_RICH_QUIET_CURVE",
    "CARRY_SUPPORTIVE_LOW_STRESS",
    "MIXED_TRANSITION",
}
STRUCTURE_VALUES = {
    "stress_tenor_scope": {"NONE", "FRONT", "MID", "BROAD"},
    "mid_curve_pressure_state": {"QUIET", "RISING", "PRICED", "RECEDING"},
    "carry_environment_state": {"OPEN", "CLOSED", "RECOVERING"},
}
TARGET_COLUMNS = {
    "event_id",
    "prediction_date",
    "event_status",
    "label",
    "label_status",
    "horizon_sessions",
    "valid_through_session",
    "outcome_available_at",
    "formal_vintage_eligible",
}
OOF_COLUMNS = {
    "event_id",
    "prediction_date",
    "outcome_available_at",
    "label",
    "label_status",
    "decision_score",
    "base_probability",
    "base_rate_at_prediction",
    "base_rate_samples",
    "base_rate_positive",
    "base_rate_negative",
    "training_samples",
    "training_positive",
    "training_negative",
    "training_latest_prediction_date",
    "training_latest_outcome_available_at",
    "converged",
    "calibrated_probability",
    "platt_a",
    "platt_b",
    "calibration_samples",
    "calibration_converged",
}


def _gate(name: str, passed: bool, **evidence: Any) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def _date(value: object) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return str(pd.Timestamp(value).date().isoformat())
    except (TypeError, ValueError):
        return None


def _is_true(value: object) -> bool:
    return value is not None and not pd.isna(value) and bool(value)


def _as_sequence(value: object) -> list[Any]:
    if isinstance(value, np.ndarray):
        return cast(list[Any], value.tolist())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _is_finite_number(value: object) -> bool:
    try:
        return bool(np.isfinite(float(cast(Any, value))))
    except (TypeError, ValueError):
        return False


def _same_number(left: object, right: object, *, tolerance: float = 1e-12) -> bool:
    if left is None or right is None:
        return left is None and right is None
    try:
        if pd.isna(left) or pd.isna(right):
            return bool(pd.isna(left) and pd.isna(right))
        return math.isclose(
            float(cast(Any, left)),
            float(cast(Any, right)),
            rel_tol=0.0,
            abs_tol=tolerance,
        )
    except (TypeError, ValueError):
        return False


def _same_timestamp(left: object, right: object) -> bool:
    if pd.isna(left) or pd.isna(right):
        return bool(pd.isna(left) and pd.isna(right))
    return bool(pd.Timestamp(left).tz_convert("UTC") == pd.Timestamp(right).tz_convert("UTC"))


def _integer_equals(value: object, expected: int) -> bool:
    numeric = cast(Any, value)
    return _is_finite_number(value) and float(numeric).is_integer() and int(numeric) == expected


def _normalize_session_frame(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    result = frame.copy()
    if column in result:
        result[column] = pd.to_datetime(result[column], errors="coerce").dt.normalize()
    return result


def _snapshot_contract_gate(snapshot: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    try:
        validate_daily_output(snapshot)
    except (TypeError, ValueError, KeyError) as exc:
        return _gate("snapshot_contract", False, error=str(exc)), False
    return _gate("snapshot_contract", True, error=None), True


def _row_has_complete_curve(row: pd.Series) -> bool:
    identifiers = _as_sequence(row.get("vx_contract_ids"))
    settlements = _as_sequence(row.get("vx_settles"))
    days = _as_sequence(row.get("vx_days_to_final"))
    return (
        len(identifiers) == 7
        and len(set(str(value) for value in identifiers)) == 7
        and len(settlements) == 7
        and all(_is_finite_number(value) and float(value) > 0 for value in settlements)
        and len(days) == 7
        and all(_is_finite_number(value) and float(value) > 0 for value in days)
        and all(float(left) < float(right) for left, right in zip(days[:-1], days[1:], strict=True))
    )


def _row_is_complete_state(row: pd.Series) -> bool:
    scores = all(
        _is_finite_number(row.get(column)) and 0.0 <= float(row[column]) <= 100.0
        for column in SCORE_COLUMNS
    )
    answers = all(str(row.get(column)) in ANSWER_VALUES[column] for column in ANSWER_COLUMNS)
    structure = all(str(row.get(column)) in values for column, values in STRUCTURE_VALUES.items())
    signature = row.get("feature_methodology_signature")
    signature_known = signature is not None and not pd.isna(signature) and bool(str(signature))
    return (
        row.get("data_status") == "OK"
        and _is_true(row.get("formal_vintage_eligible"))
        and str(row.get("pit_evidence")) in {"OBSERVED", "ASSUMED"}
        and signature_known
        and scores
        and answers
        and structure
        and str(row.get("phase")) in PHASE_VALUES
        and _row_has_complete_curve(row)
    )


def _audit_real_observations(
    observations: pd.DataFrame, snapshot_session: pd.Timestamp
) -> tuple[bool, dict[str, Any]]:
    required_columns = {
        "series_id",
        "session_date",
        "value",
        "source",
        "source_symbol",
        "available_at",
        "revision_id",
        "methodology_version",
        "vintage_kind",
    }
    missing = sorted(required_columns - set(observations.columns))
    if missing:
        return False, {"missing_columns": missing, "series": {}}

    frame = _normalize_session_frame(observations, "session_date")
    frame["available_at"] = pd.to_datetime(frame["available_at"], utc=True, errors="coerce")
    cutoff = pd.Timestamp(decision_as_of(snapshot_session)).tz_convert("UTC")
    evidence: dict[str, Any] = {}
    passed = True
    for series in REQUIRED_SERIES:
        identity = OFFICIAL_OBSERVATION_IDENTITIES[series]
        rows = frame.loc[frame["series_id"].eq(series)].copy()
        values = pd.to_numeric(rows["value"], errors="coerce")
        admitted = rows.loc[
            rows["source"].eq(identity.source)
            & rows["source_symbol"].eq(identity.source_symbol)
            & rows["vintage_kind"].eq(identity.vintage_kind)
            & rows["available_at"].notna()
            & values.notna()
            & values.gt(0)
            & rows["revision_id"].notna()
            & rows["methodology_version"].notna()
        ]
        latest = admitted.loc[
            admitted["session_date"].eq(snapshot_session) & admitted["available_at"].le(cutoff)
        ]
        valid = admitted["session_date"].nunique() >= 756 and not latest.empty
        passed &= valid
        evidence[series] = {
            "rows": len(rows),
            "formal_positive_sessions": int(admitted["session_date"].nunique()),
            "snapshot_rows_available": len(latest),
            "required_identity": {
                "source": identity.source,
                "source_symbol": identity.source_symbol,
                "vintage_kind": identity.vintage_kind,
            },
            "passed": bool(valid),
        }
    return passed, {"series": evidence, "snapshot_cutoff": cutoff.isoformat()}


def _audit_real_vx(
    vx_contracts: pd.DataFrame,
    snapshot_session: pd.Timestamp,
    latest: pd.Series,
) -> tuple[bool, dict[str, Any]]:
    required_columns = {
        "session_date",
        "contract_id",
        "settle",
        "series_id",
        "source",
        "source_symbol",
        "available_at",
        "revision_id",
        "methodology_version",
        "vintage_kind",
        "is_standard_monthly",
    }
    missing = sorted(required_columns - set(vx_contracts.columns))
    if missing:
        return False, {"missing_columns": missing}

    frame = _normalize_session_frame(vx_contracts, "session_date")
    frame["available_at"] = pd.to_datetime(frame["available_at"], utc=True, errors="coerce")
    settles = pd.to_numeric(frame["settle"], errors="coerce")
    formal = frame.loc[
        frame["source"].eq(VX_SETTLE_IDENTITY.source)
        & frame["source_symbol"].eq(VX_SETTLE_IDENTITY.source_symbol)
        & frame["series_id"].eq("VX_SETTLE")
        & frame["is_standard_monthly"].fillna(False).astype(bool)
        & frame["vintage_kind"].eq(VX_SETTLE_IDENTITY.vintage_kind)
        & frame["available_at"].notna()
        & frame["contract_id"].notna()
        & frame["revision_id"].notna()
        & frame["methodology_version"].notna()
        & settles.notna()
        & settles.gt(0)
    ].copy()
    cutoff = pd.Timestamp(decision_as_of(snapshot_session)).tz_convert("UTC")
    latest_raw = formal.loc[
        formal["session_date"].eq(snapshot_session) & formal["available_at"].le(cutoff)
    ]
    selected_ids = [str(value) for value in _as_sequence(latest.get("vx_contract_ids"))]
    selected_settles = _as_sequence(latest.get("vx_settles"))
    selected_match = len(selected_ids) == len(selected_settles) == 7
    for identifier, value in zip(selected_ids, selected_settles, strict=True):
        matches = pd.to_numeric(
            latest_raw.loc[latest_raw["contract_id"].astype(str).eq(identifier), "settle"],
            errors="coerce",
        )
        selected_match &= any(
            math.isclose(float(candidate), float(value), rel_tol=0.0, abs_tol=1e-10)
            for candidate in matches
        )
    passed = (
        formal["session_date"].nunique() >= 756
        and latest_raw["contract_id"].nunique() >= 7
        and selected_match
    )
    return passed, {
        "formal_positive_sessions": int(formal["session_date"].nunique()),
        "snapshot_contracts_available": int(latest_raw["contract_id"].nunique()),
        "selected_curve_matches_raw": bool(selected_match),
        "required_identity": {
            "source": VX_SETTLE_IDENTITY.source,
            "source_symbol": VX_SETTLE_IDENTITY.source_symbol,
            "vintage_kind": VX_SETTLE_IDENTITY.vintage_kind,
        },
        "snapshot_cutoff": cutoff.isoformat(),
    }


def _snapshot_matches_state(snapshot: dict[str, Any], latest: pd.Series) -> tuple[bool, list[str]]:
    story = snapshot.get("market_story", {})
    observations = snapshot.get("observations", {})
    differences: list[str] = []
    scalar_pairs = {
        "phase": (story.get("phase"), latest.get("phase")),
        "pressure_level": (story.get("pressure_level"), latest.get("pressure_level")),
        "direction": (story.get("direction"), latest.get("direction")),
        "baseline_score": (story.get("baseline_score"), latest.get("baseline_score")),
    }
    for name, (actual, expected) in scalar_pairs.items():
        matches = (
            _same_number(actual, expected)
            if name == "baseline_score"
            else str(actual) == str(expected)
        )
        if not matches:
            differences.append(name)

    score_map = {
        "carry_risk": "carry_risk_score",
        "shock": "shock_score",
        "tail_price": "tail_price_score",
        "persistence": "persistence_score",
        "repair": "repair_score",
    }
    for public, state_column in score_map.items():
        if not _same_number(story.get("scores", {}).get(public), latest.get(state_column)):
            differences.append(f"scores.{public}")
    answer_map = {
        "carry": "carry_answer",
        "shock": "shock_answer",
        "tail": "tail_answer",
        "persistence": "persistence_answer",
        "repair": "repair_answer",
    }
    for public, state_column in answer_map.items():
        if str(story.get("answers", {}).get(public)) != str(latest.get(state_column)):
            differences.append(f"answers.{public}")
    for field in STRUCTURE_VALUES:
        if str(story.get("structure", {}).get(field)) != str(latest.get(field)):
            differences.append(f"structure.{field}")
    for field in ("vx_contract_ids", "vx_settles", "vx_days_to_final"):
        actual = _as_sequence(observations.get(field))
        expected = _as_sequence(latest.get(field))
        if field == "vx_contract_ids":
            matches = [str(value) for value in actual] == [str(value) for value in expected]
        else:
            matches = len(actual) == len(expected) and all(
                _same_number(left, right) for left, right in zip(actual, expected, strict=True)
            )
        if not matches:
            differences.append(f"observations.{field}")
    return not differences, differences


def _audit_target_ledger(
    targets: pd.DataFrame, states: pd.DataFrame
) -> tuple[bool, dict[str, Any], pd.DataFrame]:
    missing = sorted(TARGET_COLUMNS - set(targets.columns))
    if missing:
        return False, {"missing_columns": missing}, targets.copy()
    ledger = _normalize_session_frame(targets, "prediction_date")
    ledger["valid_through_session"] = pd.to_datetime(
        ledger["valid_through_session"], errors="coerce"
    ).dt.normalize()
    ledger["outcome_available_at"] = pd.to_datetime(
        ledger["outcome_available_at"], utc=True, errors="coerce"
    )
    event_set = set(ledger["event_id"].dropna())
    state_dates = set(pd.to_datetime(states["session_date"]).dt.normalize())
    exact_keys = (
        len(ledger) == len(states) * len(EVENT_ORDER)
        and event_set == set(EVENT_ORDER)
        and set(ledger["prediction_date"].dropna()) == state_dates
    )

    statuses = add_event_statuses(states)
    status_lookup: dict[tuple[str, pd.Timestamp], str] = {}
    for event in EVENT_ORDER:
        for row in statuses[["session_date", f"{event}__event_status"]].itertuples(index=False):
            status_lookup[(event, pd.Timestamp(row[0]).normalize())] = str(row[1])
    event_status_matches = all(
        status_lookup.get((str(row.event_id), pd.Timestamp(row.prediction_date).normalize()))
        == str(row.event_status)
        for row in ledger.itertuples(index=False)
        if pd.notna(row.prediction_date)
    )

    completed = ledger["label_status"].isin(["OBSERVED_0", "OBSERVED_1"])
    not_applicable = ledger["label_status"].eq("NOT_APPLICABLE")
    censored = ledger["label_status"].eq("CENSORED")
    numeric_labels = pd.to_numeric(ledger["label"], errors="coerce")
    completed_truth = bool(
        (
            ledger.loc[completed, "event_status"].eq("ELIGIBLE")
            & numeric_labels.loc[completed].isin([0, 1])
            & ledger.loc[completed, "valid_through_session"].notna()
            & ledger.loc[completed, "outcome_available_at"].notna()
            & ledger.loc[completed, "formal_vintage_eligible"].fillna(False).astype(bool)
        ).all()
    )
    null_label_truth = bool(
        numeric_labels.loc[not_applicable | censored].isna().all()
        and ledger.loc[not_applicable, "event_status"].eq("NOT_APPLICABLE").all()
        and ledger.loc[not_applicable | censored, "outcome_available_at"].isna().all()
    )

    horizon_truth = True
    for row in ledger.loc[completed].itertuples(index=False):
        expected_horizon = EVENT_HORIZONS[str(row.event_id)]
        expected_end = add_sessions(row.prediction_date, expected_horizon)
        expected_available = pd.Timestamp(decision_as_of(expected_end)).tz_convert("UTC")
        horizon_truth &= _integer_equals(row.horizon_sessions, expected_horizon)
        horizon_truth &= pd.Timestamp(row.valid_through_session).normalize() == expected_end
        horizon_truth &= _same_timestamp(row.outcome_available_at, expected_available)

    duplicate_count = int(ledger.duplicated(["event_id", "prediction_date"]).sum())
    passed = bool(
        duplicate_count == 0
        and exact_keys
        and event_status_matches
        and (completed | not_applicable | censored).all()
        and completed_truth
        and null_label_truth
        and horizon_truth
    )
    return (
        passed,
        {
            "rows": len(ledger),
            "expected_rows": len(states) * len(EVENT_ORDER),
            "duplicate_keys": duplicate_count,
            "event_set": sorted(event_set),
            "event_status_matches_state": bool(event_status_matches),
            "completed_rows": int(completed.sum()),
            "completed_truth": completed_truth,
            "null_label_truth": null_label_truth,
            "horizon_truth": bool(horizon_truth),
        },
        ledger,
    )


def _event_cohort_evidence(
    targets: pd.DataFrame,
    states: pd.DataFrame,
    event: str,
    snapshot_session: pd.Timestamp,
    spec: ProbabilitySpec,
) -> dict[str, Any]:
    cutoff_time = pd.Timestamp(decision_as_of(snapshot_session)).tz_convert("UTC")
    event_rows = targets.loc[targets["event_id"].eq(event)].copy()
    completed = event_rows.loc[
        event_rows["label_status"].isin(["OBSERVED_0", "OBSERVED_1"])
        & event_rows["outcome_available_at"].le(cutoff_time)
        & event_rows["prediction_date"].lt(snapshot_session)
    ].sort_values("prediction_date")
    labels = pd.to_numeric(completed["label"], errors="coerce")
    positives = int(labels.sum())
    negatives = len(completed) - positives

    source = states[["session_date", *LOGISTIC_FEATURES[event]]].rename(
        columns={"session_date": "prediction_date"}
    )
    training = completed.merge(source, on="prediction_date", how="left")
    training = training.loc[
        training["prediction_date"].le(add_sessions(snapshot_session, -spec.purge_sessions))
    ].dropna(subset=[*LOGISTIC_FEATURES[event], "label"])
    training = training.tail(spec.training_max)
    training_positive = int(training["label"].sum())
    training_negative = len(training) - training_positive
    return {
        "completed": len(completed),
        "positive": positives,
        "negative": negatives,
        "base_rate_ready": len(completed) >= spec.base_rate_min,
        "training_samples": len(training),
        "training_positive": training_positive,
        "training_negative": training_negative,
        "logistic_ready": bool(
            len(training) >= spec.training_min
            and training_positive >= spec.training_min_positive
            and training_negative >= spec.training_min_negative
        ),
    }


def _audit_oof_training_boundaries(
    states: pd.DataFrame,
    targets: pd.DataFrame,
    oof: pd.DataFrame,
    spec: ProbabilitySpec,
) -> tuple[bool, dict[str, Any], pd.DataFrame]:
    missing = sorted(OOF_COLUMNS - set(oof.columns))
    if missing:
        return False, {"missing_columns": missing, "rows": len(oof)}, oof.copy()
    ledger = _normalize_session_frame(oof, "prediction_date")
    ledger["outcome_available_at"] = pd.to_datetime(
        ledger["outcome_available_at"], utc=True, errors="coerce"
    )
    ledger["training_latest_outcome_available_at"] = pd.to_datetime(
        ledger["training_latest_outcome_available_at"], utc=True, errors="coerce"
    )
    ledger["training_latest_prediction_date"] = pd.to_datetime(
        ledger["training_latest_prediction_date"], errors="coerce"
    ).dt.normalize()
    unknown_events = set(ledger["event_id"].dropna()) - set(EVENT_ORDER)
    violations: list[str] = []

    for event in EVENT_ORDER:
        features = LOGISTIC_FEATURES[event]
        source = states[["session_date", *features]].rename(
            columns={"session_date": "prediction_date"}
        )
        event_targets = (
            targets.loc[targets["event_id"].eq(event)]
            .merge(source, on="prediction_date", how="left")
            .sort_values("prediction_date")
        )
        target_index = event_targets.set_index("prediction_date", drop=False)
        event_oof = ledger.loc[ledger["event_id"].eq(event)].sort_values("prediction_date")
        for row in event_oof.itertuples(index=False):
            prediction_date = pd.Timestamp(row.prediction_date).normalize()
            prefix = f"{event}@{prediction_date.date()}"
            if prediction_date not in target_index.index:
                violations.append(f"{prefix}: target row missing")
                continue
            target_row = target_index.loc[prediction_date]
            if isinstance(target_row, pd.DataFrame):
                violations.append(f"{prefix}: target key duplicated")
                continue
            if target_row["event_status"] != "ELIGIBLE":
                violations.append(f"{prefix}: OOF prediction was not ELIGIBLE")

            as_of = pd.Timestamp(decision_as_of(prediction_date)).tz_convert("UTC")
            completed = event_targets.loc[
                event_targets["label_status"].isin(["OBSERVED_0", "OBSERVED_1"])
                & event_targets["outcome_available_at"].le(as_of)
                & event_targets["prediction_date"].lt(prediction_date)
            ].sort_values("prediction_date")
            training = completed.loc[
                completed["prediction_date"].le(add_sessions(prediction_date, -spec.purge_sessions))
            ]
            sample = training.dropna(subset=[*features, "label"]).tail(spec.training_max)
            positives = int(sample["label"].sum())
            negatives = len(sample) - positives
            if not (
                _integer_equals(row.training_samples, len(sample))
                and _integer_equals(row.training_positive, positives)
                and _integer_equals(row.training_negative, negatives)
                and len(sample) >= spec.training_min
                and positives >= spec.training_min_positive
                and negatives >= spec.training_min_negative
                and _is_true(row.converged)
            ):
                violations.append(f"{prefix}: training cohort metadata mismatch")

            expected_latest_date = training["prediction_date"].max()
            expected_latest_outcome = training["outcome_available_at"].max()
            if not (
                pd.Timestamp(row.training_latest_prediction_date).normalize()
                == pd.Timestamp(expected_latest_date).normalize()
                and _same_timestamp(
                    row.training_latest_outcome_available_at, expected_latest_outcome
                )
            ):
                violations.append(f"{prefix}: persisted training boundary mismatch")

            rate, count, base_positive, base_negative = beta_smoothed_base_rate(
                completed["label"],
                max_samples=spec.base_rate_max,
                minimum_samples=spec.base_rate_min,
            )
            if not (
                _integer_equals(row.base_rate_samples, count)
                and _integer_equals(row.base_rate_positive, base_positive)
                and _integer_equals(row.base_rate_negative, base_negative)
                and _same_number(row.base_rate_at_prediction, rate)
            ):
                violations.append(f"{prefix}: rolling BaseRate metadata mismatch")
            if not (
                _is_finite_number(row.decision_score)
                and _is_finite_number(row.base_probability)
                and 0.0 < float(row.base_probability) < 1.0
            ):
                violations.append(f"{prefix}: raw logistic output invalid")

            if (
                str(row.label_status) != str(target_row["label_status"])
                or not _same_number(row.label, target_row["label"])
                or not _same_timestamp(row.outcome_available_at, target_row["outcome_available_at"])
            ):
                violations.append(f"{prefix}: refreshed outcome differs from target ledger")

    duplicate_count = int(ledger.duplicated(["event_id", "prediction_date"]).sum())
    passed = duplicate_count == 0 and not unknown_events and not violations and bool(len(ledger))
    return (
        passed,
        {
            "rows": len(ledger),
            "duplicate_keys": duplicate_count,
            "unknown_events": sorted(unknown_events),
            "violations": len(violations),
            "first_violations": violations[:10],
        },
        ledger,
    )


def _platt_row_is_arithmetically_valid(row: pd.Series) -> bool:
    if not _is_true(row.get("calibration_converged")):
        return bool(pd.isna(row.get("calibrated_probability")))
    values = (
        row.get("decision_score"),
        row.get("platt_a"),
        row.get("platt_b"),
        row.get("calibrated_probability"),
    )
    if not all(_is_finite_number(value) for value in values):
        return False
    expected = apply_platt(
        float(row["decision_score"]), float(row["platt_a"]), float(row["platt_b"])
    )
    return _same_number(row["calibrated_probability"], expected)


def _completed_calibrated_validation(
    oof: pd.DataFrame, event: str, snapshot_session: pd.Timestamp
) -> tuple[bool, dict[str, Any]]:
    if oof.empty:
        return False, {"samples": 0, "accepted": False}
    frame = oof.loc[oof["event_id"].eq(event)].copy() if "event_id" in oof else oof.copy()
    cutoff = pd.Timestamp(decision_as_of(snapshot_session)).tz_convert("UTC")
    completed = frame.loc[
        frame["label_status"].isin(["OBSERVED_0", "OBSERVED_1"])
        & frame["calibrated_probability"].notna()
        & frame["base_rate_at_prediction"].notna()
        & pd.to_datetime(frame["outcome_available_at"], utc=True, errors="coerce").le(cutoff)
        & pd.to_datetime(frame["prediction_date"], errors="coerce").lt(snapshot_session)
    ].sort_values("prediction_date")
    metrics = acceptance_metrics(completed)
    complete = bool(
        metrics.get("samples") == 252
        and int(metrics.get("positives", 0)) >= 20
        and int(metrics.get("negatives", 0)) >= 20
        and {"brier_model", "brier_base", "brier_skill", "ece"}.issubset(metrics)
    )
    return complete, {**metrics, "completed_calibrated_available": len(completed)}


def _calibration_integrity_passes(
    event_evidence: dict[str, dict[str, Any]], violations: list[str]
) -> bool:
    """Separate replay integrity from whether a feature model earns publication."""

    return (
        not violations
        and set(event_evidence) == set(EVENT_ORDER)
        and all(
            evidence["raw_oof"] > 0 and evidence["calibrated_oof"] > 0
            for evidence in event_evidence.values()
        )
    )


def _audit_sequential_calibration(
    oof: pd.DataFrame,
    snapshot_session: pd.Timestamp,
    spec: ProbabilitySpec,
) -> tuple[bool, dict[str, Any]]:
    violations: list[str] = []
    event_evidence: dict[str, Any] = {}
    for event in EVENT_ORDER:
        event_oof = oof.loc[oof["event_id"].eq(event)].sort_values("prediction_date")
        calibrated_total = int(event_oof["calibrated_probability"].notna().sum())
        for index, (_, row) in enumerate(event_oof.iterrows()):
            prediction_date = pd.Timestamp(row["prediction_date"]).normalize()
            as_of = pd.Timestamp(decision_as_of(prediction_date)).tz_convert("UTC")
            prior = event_oof.iloc[:index]
            prior = prior.loc[
                prior["label_status"].isin(["OBSERVED_0", "OBSERVED_1"])
                & prior["outcome_available_at"].le(as_of)
            ].tail(spec.calibration_max)
            positives = int(prior["label"].sum()) if not prior.empty else 0
            negatives = len(prior) - positives
            ready = (
                len(prior) >= spec.calibration_min_positive + spec.calibration_min_negative
                and positives >= spec.calibration_min_positive
                and negatives >= spec.calibration_min_negative
            )
            prefix = f"{event}@{prediction_date.date()}"
            converged_is_boolean = isinstance(row["calibration_converged"], (bool, np.bool_))
            if not converged_is_boolean:
                violations.append(f"{prefix}: calibration convergence flag is not boolean")
            if not _integer_equals(row["calibration_samples"], len(prior)):
                violations.append(f"{prefix}: calibration_samples is not prior-only cohort")
            if not ready and (
                _is_true(row["calibration_converged"])
                or pd.notna(row["calibrated_probability"])
                or pd.notna(row["platt_a"])
                or pd.notna(row["platt_b"])
            ):
                violations.append(f"{prefix}: Platt published before class minimum")
            if ready and not _platt_row_is_arithmetically_valid(row):
                violations.append(f"{prefix}: calibrated probability disagrees with Platt")

        validation_complete, validation = _completed_calibrated_validation(
            event_oof, event, snapshot_session
        )
        event_evidence[event] = {
            "raw_oof": len(event_oof),
            "calibrated_oof": calibrated_total,
            "validation_complete": validation_complete,
            "validation": validation,
        }
    return _calibration_integrity_passes(event_evidence, violations), {
        "events": event_evidence,
        "violations": len(violations),
        "first_violations": violations[:10],
    }


def _events_equal(actual: dict[str, Any], expected: dict[str, Any]) -> tuple[bool, list[str]]:
    differences: list[str] = []
    numeric = {"probability", "base_rate", "uplift"}
    for field in {
        "event_status",
        "model_status",
        "probability_kind",
        "probability",
        "base_rate",
        "uplift",
        "valid_through_session",
        "interpretation",
    }:
        matches = (
            _same_number(actual.get(field), expected.get(field))
            if field in numeric
            else actual.get(field) == expected.get(field)
        )
        if not matches:
            differences.append(field)
    return not differences, differences


def _audit_probability_publication(
    states: pd.DataFrame,
    targets: pd.DataFrame,
    oof: pd.DataFrame,
    snapshot: dict[str, Any],
    snapshot_session: pd.Timestamp,
    spec: ProbabilitySpec,
) -> tuple[bool, dict[str, Any]]:
    actual_events = snapshot.get("probability_judgment", {})
    event_evidence: dict[str, Any] = {}
    expected_events: dict[str, dict[str, Any]] = {}
    passed = set(actual_events) == set(EVENT_ORDER)
    for event in EVENT_ORDER:
        event_oof = oof.loc[oof["event_id"].eq(event)].copy()
        try:
            expected, metadata, _ = probability_for_event(
                states,
                targets,
                event,
                snapshot_session,
                oof=event_oof,
                spec=spec,
                formal_runtime_required=True,
            )
            matches, differences = _events_equal(actual_events.get(event, {}), expected)
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            expected = {}
            metadata = {"error": str(exc)}
            matches = False
            differences = ["recompute_failed"]
        passed &= matches
        expected_events[event] = expected
        event_evidence[event] = {
            "matches_recomputed_publication": matches,
            "differences": differences,
            "actual_status": actual_events.get(event, {}).get("model_status"),
            "expected_status": expected.get("model_status"),
            "fallback_reason": metadata.get("fallback_reason"),
            "validation": metadata.get("validation"),
        }
    expected_outlook = outlook_answer(str(snapshot.get("data_status")), expected_events)
    actual_outlook = snapshot.get("market_story", {}).get("answers", {}).get("outlook")
    outlook_matches = actual_outlook == expected_outlook
    probability_failed = "PROBABILITY_JOB_FAILED" in snapshot.get("issues", [])
    passed &= outlook_matches and not probability_failed
    return passed, {
        "events": event_evidence,
        "outlook": {
            "actual": actual_outlook,
            "expected": expected_outlook,
            "matches": outlook_matches,
        },
        "probability_job_failed": probability_failed,
    }


def build_real_acceptance_report(
    *,
    observations: pd.DataFrame,
    vx_contracts: pd.DataFrame,
    states: pd.DataFrame,
    targets: pd.DataFrame,
    oof: pd.DataFrame,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Verify the real market-state and probability chain from persisted artifacts."""

    gates: list[dict[str, Any]] = []
    contract_gate, snapshot_valid = _snapshot_contract_gate(snapshot)
    gates.append(contract_gate)
    spec = ProbabilitySpec()
    runtime = runtime_contract_status()
    gates.append(_gate("formal_probability_runtime", bool(runtime["compatible"]), **runtime))

    state = _normalize_session_frame(states, "session_date")
    valid_state_dates = "session_date" in state and state["session_date"].notna().all()
    unique_state_dates = valid_state_dates and not state["session_date"].duplicated().any()
    gates.append(
        _gate(
            "state_session_integrity",
            bool(len(state)) and unique_state_dates,
            rows=len(state),
            invalid_dates=(
                int(state["session_date"].isna().sum()) if "session_date" in state else len(state)
            ),
            duplicate_dates=(
                int(state["session_date"].duplicated().sum()) if "session_date" in state else 0
            ),
        )
    )

    parsed_snapshot_session = pd.to_datetime(snapshot.get("session_date"), errors="coerce")
    snapshot_session = (
        pd.Timestamp(parsed_snapshot_session).normalize()
        if pd.notna(parsed_snapshot_session)
        else pd.NaT
    )
    complete_mask = (
        state.apply(_row_is_complete_state, axis=1)
        if len(state) and "session_date" in state
        else pd.Series(False, index=state.index)
    )
    complete_rows = state.loc[complete_mask]
    latest_complete_session = (
        pd.Timestamp(complete_rows["session_date"].max()).normalize()
        if not complete_rows.empty
        else pd.NaT
    )
    latest_rows = (
        state.loc[state["session_date"].eq(snapshot_session)]
        if pd.notna(snapshot_session) and "session_date" in state
        else pd.DataFrame()
    )
    latest = latest_rows.iloc[-1] if not latest_rows.empty else pd.Series(dtype=object)
    latest_complete = (
        not latest.empty
        and _row_is_complete_state(latest)
        and pd.notna(latest_complete_session)
        and snapshot_session == latest_complete_session
    )
    gates.append(
        _gate(
            "latest_complete_state",
            latest_complete,
            snapshot_session=_date(snapshot_session),
            latest_complete_session=_date(latest_complete_session),
            state_last_session=(
                _date(state["session_date"].max())
                if "session_date" in state and len(state)
                else None
            ),
            data_status=latest.get("data_status"),
            curve_contracts=len(_as_sequence(latest.get("vx_contract_ids"))),
        )
    )

    status_series = state.get("data_status", pd.Series(index=state.index, dtype=object))
    ok_rows = state.loc[status_series.eq("OK")]
    state_violations: list[str] = []
    for _, series in ok_rows.iterrows():
        for column in SCORE_COLUMNS:
            if not (
                _is_finite_number(series.get(column)) and 0.0 <= float(series[column]) <= 100.0
            ):
                state_violations.append(f"{_date(series.get('session_date'))}:{column}")
        for column in ANSWER_COLUMNS:
            if str(series.get(column)) not in ANSWER_VALUES[column]:
                state_violations.append(f"{_date(series.get('session_date'))}:{column}")
        for column, values in STRUCTURE_VALUES.items():
            if str(series.get(column)) not in values:
                state_violations.append(f"{_date(series.get('session_date'))}:{column}")
        if str(series.get("phase")) not in PHASE_VALUES:
            state_violations.append(f"{_date(series.get('session_date'))}:phase")
    gates.append(
        _gate(
            "ok_state_business_truth",
            bool(len(ok_rows)) and not state_violations,
            ok_rows=len(ok_rows),
            violations=len(state_violations),
            first_violations=state_violations[:10],
            phase_counts=(ok_rows["phase"].value_counts().to_dict() if "phase" in ok_rows else {}),
        )
    )

    snapshot_matches, snapshot_differences = (
        _snapshot_matches_state(snapshot, latest)
        if snapshot_valid and not latest.empty
        else (False, ["snapshot_or_state_unavailable"])
    )
    gates.append(
        _gate(
            "snapshot_matches_latest_state",
            snapshot_matches,
            differences=snapshot_differences,
        )
    )

    if pd.notna(snapshot_session):
        observation_passed, observation_evidence = _audit_real_observations(
            observations, snapshot_session
        )
        vx_passed, vx_evidence = _audit_real_vx(vx_contracts, snapshot_session, latest)
    else:
        observation_passed, observation_evidence = False, {"error": "invalid snapshot date"}
        vx_passed, vx_evidence = False, {"error": "invalid snapshot date"}
    gates.append(_gate("core_series_real_coverage", observation_passed, **observation_evidence))
    gates.append(_gate("standard_monthly_vx_real_coverage", vx_passed, **vx_evidence))

    target_passed = False
    normalized_targets = targets.copy()
    if unique_state_dates:
        try:
            target_passed, target_evidence, normalized_targets = _audit_target_ledger(
                targets, state
            )
        except (KeyError, TypeError, ValueError) as exc:
            target_evidence = {"error": str(exc)}
    else:
        target_evidence = {"error": "state session integrity failed"}
    gates.append(_gate("target_ledger_truth", target_passed, **target_evidence))

    cohort_evidence: dict[str, Any] = {}
    cohort_passed = target_passed and pd.notna(snapshot_session)
    if cohort_passed:
        for event in EVENT_ORDER:
            evidence = _event_cohort_evidence(
                normalized_targets, state, event, snapshot_session, spec
            )
            cohort_evidence[event] = evidence
            cohort_passed &= bool(evidence["base_rate_ready"])
    gates.append(_gate("five_event_target_cohorts", cohort_passed, events=cohort_evidence))

    oof_passed = False
    normalized_oof = oof.copy()
    if target_passed:
        try:
            oof_passed, oof_evidence, normalized_oof = _audit_oof_training_boundaries(
                state, normalized_targets, oof, spec
            )
        except (KeyError, TypeError, ValueError) as exc:
            oof_evidence = {"error": str(exc), "rows": len(oof)}
    else:
        oof_evidence = {"error": "target ledger truth failed", "rows": len(oof)}
    gates.append(_gate("oof_training_boundaries", oof_passed, **oof_evidence))

    calibration_passed = False
    if oof_passed and pd.notna(snapshot_session):
        try:
            calibration_passed, calibration_evidence = _audit_sequential_calibration(
                normalized_oof, snapshot_session, spec
            )
        except (KeyError, TypeError, ValueError) as exc:
            calibration_evidence = {"error": str(exc)}
    else:
        calibration_evidence = {"error": "OOF boundary gate failed"}
    gates.append(
        _gate(
            "five_event_oof_calibration_integrity",
            calibration_passed,
            **calibration_evidence,
        )
    )

    publication_passed = False
    if snapshot_valid and latest_complete and target_passed and oof_passed:
        publication_passed, publication_evidence = _audit_probability_publication(
            state,
            normalized_targets,
            normalized_oof,
            snapshot,
            snapshot_session,
            spec,
        )
    else:
        publication_evidence = {
            "error": "snapshot, latest state, target, or OOF prerequisite failed"
        }
    gates.append(_gate("probability_publication_truth", publication_passed, **publication_evidence))

    return {
        "acceptance_version": "2.0.0",
        "passed": all(gate["passed"] for gate in gates),
        "session_date": snapshot.get("session_date"),
        "data_range": {
            "state_first": (
                _date(state["session_date"].min())
                if "session_date" in state and len(state)
                else None
            ),
            "state_last": (
                _date(state["session_date"].max())
                if "session_date" in state and len(state)
                else None
            ),
            "state_rows": len(state),
        },
        "gates": gates,
    }


def write_real_acceptance_report(report: dict[str, Any], path: str | Path) -> Path:
    return write_json(report, path)


def failed_gate_names(report: dict[str, Any]) -> Iterable[str]:
    return (str(gate["name"]) for gate in report.get("gates", []) if not bool(gate.get("passed")))
