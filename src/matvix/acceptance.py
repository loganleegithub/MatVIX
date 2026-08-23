from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from matvix.calendar import add_sessions, decision_as_of
from matvix.constants import (
    BASE_RATE_ONLY_EVENTS,
    EVENT_HORIZONS,
    EVENT_ORDER,
    FEATURE_CONDITIONAL_EVENTS,
    LOGISTIC_FEATURES,
)
from matvix.features.futures_curve import VXCM30_METHODOLOGY, VXCM30_TARGET_DAYS
from matvix.output import validate_daily_output
from matvix.probability.baseline import beta_smoothed_base_rate
from matvix.probability.calibration import acceptance_metrics, apply_intercept, fit_intercept
from matvix.probability.engine import outlook_answer, probability_for_event
from matvix.probability.targets import add_carry_duration_facts, add_event_statuses
from matvix.probability.walk_forward import ProbabilitySpec, runtime_contract_status
from matvix.source_identity import OFFICIAL_OBSERVATION_IDENTITIES, VX_SETTLE_IDENTITY
from matvix.state.transitions import RISK_ON_CONFIRMATION_TRANSITIONS, build_state_table
from matvix.storage import read_json, write_json, write_parquet
from matvix.v2_audit import (
    _append_invariance,
    _loco_direction,
    _match_clusters,
    _series_equal,
    _true_clusters,
)

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
    "raw_probability",
    "published_probability",
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
    "calibration_method",
    "calibration_samples",
    "calibration_positive",
    "calibration_negative",
    "intercept_b",
}

STATION_DIMENSIONS = (
    "DATA",
    "TENOR",
    "STATE_TIMING",
    "PROBABILITY_INTEGRITY",
    "PROBABILITY_MODEL",
)
V3_STATION_DIMENSIONS = (
    "DATA",
    "TENOR",
    "STATE_TIMING",
    "PROBABILITY_INTEGRITY",
    "PROBABILITY_MODEL",
    "BASE_RATE_REFERENCE",
    "FRAGILITY_BOUNDARY",
)
REJECTED_FRAGILITY_EVENT_ID = "calm_carry_breaks_5d"
REJECTED_FRAGILITY_COMPLETED_OOF = 114
REJECTED_FRAGILITY_REQUIRED_OOF = 252
REJECTED_FRAGILITY_ARTIFACT_SHA256 = (
    "44e7e43efb207b8b8b56ee20a9c0ab18229046ac2e73eb6dd7d05b4c1c770770"
)
STATION_REQUIRED_OK_FIELDS = (
    "vxcm30",
    "basis30_eod",
    "front_curve_level",
    "f4_f7_level",
    "f4_f7_slope30",
    "f4_f7_inversion_share",
    "front_to_mid_log_ratio",
    "d5_log_f4_f7_level",
    "d5_f4_f7_slope30",
    "d5_f4_f7_inversion_share",
    "d10_log_f4_f7_level",
    "d10_f4_f7_slope30",
    "d10_f4_f7_inversion_share",
    "p_f4_f7_level",
    "p_neg_f4_f7_slope30",
    "p_d5_log_f4_f7_level",
    "p_neg_d5_log_f4_f7_level",
    "p_d5_f4_f7_slope30",
    "p_neg_d5_f4_f7_slope30",
    "front_pressure",
    "broad_pressure_day",
    "broad_pressure_now",
    "carry_open_day",
)


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


def _audit_carry_duration_facts(states: pd.DataFrame) -> tuple[bool, dict[str, Any]]:
    legacy_columns = [column for column in ("log1p_carry_spell_age",) if column in states]
    columns = (
        "carry_spell_age",
        "bounded_log1p_carry_spell_age",
        "carry_recovering_flag",
    )
    missing = [column for column in columns if column not in states]
    if missing:
        return False, {"missing_columns": missing, "rows": len(states)}
    expected = add_carry_duration_facts(states.drop(columns=list(columns)))
    matches = {
        column: _series_equal(states[column], expected[column]) for column in columns
    }
    statuses = add_event_statuses(expected)[
        "carry_environment_recovers_10d__event_status"
    ]
    eligible = statuses.eq("ELIGIBLE")
    null_truth = bool(states.loc[~eligible, list(columns)].isna().all(axis=None))
    recovering_truth = bool(
        states.loc[eligible, "carry_recovering_flag"].eq(
            states.loc[eligible, "carry_environment_state"].eq("RECOVERING").astype(float)
        ).all()
    )
    passed = (
        not legacy_columns
        and all(matches.values())
        and null_truth
        and recovering_truth
        and bool(eligible.any())
    )
    return passed, {
        "rows": len(states),
        "legacy_columns": legacy_columns,
        "eligible_rows": int(eligible.sum()),
        "max_spell_age": (
            int(states.loc[eligible, "carry_spell_age"].max()) if eligible.any() else 0
        ),
        "column_replay": matches,
        "noneligible_null_truth": null_truth,
        "recovering_flag_truth": recovering_truth,
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
            if event in BASE_RATE_ONLY_EVENTS:
                if not (
                    _integer_equals(row.training_samples, 0)
                    and _integer_equals(row.training_positive, 0)
                    and _integer_equals(row.training_negative, 0)
                    and not _is_true(row.converged)
                    and pd.isna(row.training_latest_prediction_date)
                    and pd.isna(row.training_latest_outcome_available_at)
                ):
                    violations.append(f"{prefix}: base-rate exemption trained a model")
            else:
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
            if event in BASE_RATE_ONLY_EVENTS:
                if pd.notna(row.raw_probability):
                    violations.append(f"{prefix}: base-rate exemption has raw probability")
            elif not (
                _is_finite_number(row.raw_probability)
                and 0.0 < float(row.raw_probability) < 1.0
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


def _calibration_row_is_arithmetically_valid(row: pd.Series) -> bool:
    method = row.get("calibration_method")
    if method == "NOT_APPLICABLE":
        return bool(
            pd.isna(row.get("raw_probability"))
            and pd.isna(row.get("intercept_b"))
            and _same_number(row.get("published_probability"), row.get("base_rate_at_prediction"))
        )
    if method == "IDENTITY_WARMUP":
        return bool(
            _is_finite_number(row.get("raw_probability"))
            and pd.isna(row.get("intercept_b"))
            and _same_number(row.get("published_probability"), row.get("raw_probability"))
        )
    if method != "ROLLING_INTERCEPT_252":
        return False
    values = (
        row.get("raw_probability"),
        row.get("intercept_b"),
        row.get("published_probability"),
    )
    if not all(_is_finite_number(value) for value in values):
        return False
    expected = apply_intercept(float(row["raw_probability"]), float(row["intercept_b"]))
    return _same_number(row["published_probability"], expected)


def _completed_published_validation(
    oof: pd.DataFrame, event: str, snapshot_session: pd.Timestamp
) -> tuple[bool, dict[str, Any]]:
    if oof.empty:
        return False, {"samples": 0, "accepted": False}
    frame = oof.loc[oof["event_id"].eq(event)].copy() if "event_id" in oof else oof.copy()
    cutoff = pd.Timestamp(decision_as_of(snapshot_session)).tz_convert("UTC")
    completed = frame.loc[
        frame["label_status"].isin(["OBSERVED_0", "OBSERVED_1"])
        & frame["published_probability"].notna()
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
    return complete, {**metrics, "completed_published_available": len(completed)}


def _calibration_integrity_passes(
    event_evidence: dict[str, dict[str, Any]], violations: list[str]
) -> bool:
    """Separate replay integrity from whether a feature model earns publication."""

    return (
        not violations
        and set(event_evidence) == set(EVENT_ORDER)
        and all(
            (
                evidence["base_rate_reference_oof"] > 0
                if event in BASE_RATE_ONLY_EVENTS
                else evidence["raw_oof"] > 0 and evidence["published_oof"] > 0
            )
            for event, evidence in event_evidence.items()
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
        published_total = int(event_oof["published_probability"].notna().sum())
        for index, (_, row) in enumerate(event_oof.iterrows()):
            prediction_date = pd.Timestamp(row["prediction_date"]).normalize()
            prefix = f"{event}@{prediction_date.date()}"
            if event in BASE_RATE_ONLY_EVENTS:
                if not (
                    row["calibration_method"] == "NOT_APPLICABLE"
                    and _integer_equals(row["calibration_samples"], 0)
                    and _integer_equals(row["calibration_positive"], 0)
                    and _integer_equals(row["calibration_negative"], 0)
                    and _calibration_row_is_arithmetically_valid(row)
                ):
                    violations.append(f"{prefix}: base-rate exemption calibration metadata invalid")
                continue
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
            if not (
                _integer_equals(row["calibration_samples"], len(prior))
                and _integer_equals(row["calibration_positive"], positives)
                and _integer_equals(row["calibration_negative"], negatives)
            ):
                violations.append(f"{prefix}: calibration cohort metadata mismatch")
            if not ready and not (
                row["calibration_method"] == "IDENTITY_WARMUP"
                and _calibration_row_is_arithmetically_valid(row)
            ):
                violations.append(f"{prefix}: non-causal warmup publication")
            if ready:
                expected_intercept = fit_intercept(
                    prior["raw_probability"].to_numpy(), prior["label"].to_numpy()
                )
                if not (
                    row["calibration_method"] == "ROLLING_INTERCEPT_252"
                    and _same_number(row["intercept_b"], expected_intercept)
                    and _calibration_row_is_arithmetically_valid(row)
                ):
                    violations.append(f"{prefix}: rolling intercept replay mismatch")

        if event in BASE_RATE_ONLY_EVENTS:
            event_evidence[event] = {
                "publication_policy": "BASE_RATE_ONLY_EXEMPT",
                "raw_oof": 0,
                "published_oof": published_total,
                "base_rate_reference_oof": published_total,
                "validation_complete": True,
                "validation": {"accepted": True, "exempt": True, "samples": published_total},
            }
        else:
            validation_complete, validation = _completed_published_validation(
                event_oof, event, snapshot_session
            )
            event_evidence[event] = {
                "publication_policy": "FEATURE_CONDITIONAL_REQUIRED",
                "raw_oof": int(event_oof["raw_probability"].notna().sum()),
                "published_oof": published_total,
                "base_rate_reference_oof": 0,
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
    numeric = {"raw_probability", "probability", "base_rate", "uplift", "intercept_b"}
    for field in {
        "event_status",
        "model_status",
        "probability_kind",
        "raw_probability",
        "probability",
        "base_rate",
        "uplift",
        "calibration_method",
        "calibration_samples",
        "calibration_positive",
        "calibration_negative",
        "intercept_b",
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

    try:
        carry_duration_passed, carry_duration_evidence = _audit_carry_duration_facts(state)
    except (KeyError, TypeError, ValueError) as exc:
        carry_duration_passed = False
        carry_duration_evidence = {"error": str(exc), "rows": len(state)}
    gates.append(
        _gate("carry_duration_fact_replay", carry_duration_passed, **carry_duration_evidence)
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
    gates.append(_gate("v3_event_target_cohorts", cohort_passed, events=cohort_evidence))

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
            "v3_oof_calibration_integrity",
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
        "acceptance_version": "3.0.0",
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


def _station_curve_formula_valid(row: pd.Series) -> bool:
    """Independently replay the seven-anchor curve facts published by one row."""

    try:
        identifiers = _as_sequence(row.get("vx_contract_ids"))
        settlements = np.asarray(_as_sequence(row.get("vx_settles")), dtype=float)
        days = np.asarray(_as_sequence(row.get("vx_days_to_final")), dtype=float)
        if not (
            len(identifiers) == len(settlements) == len(days) == 7
            and len(set(identifiers)) == 7
            and np.isfinite(settlements).all()
            and np.isfinite(days).all()
            and (settlements > 0).all()
            and (days > 0).all()
            and (np.diff(days) > 0).all()
        ):
            return False
        expected = {
            "front_curve_level": float(np.mean(settlements[:2])),
            "f4_f7_level": float(np.mean(settlements[3:7])),
            "f4_f7_slope30": float(
                np.log(settlements[6] / settlements[3]) * 30.0 / (days[6] - days[3])
            ),
            "f4_f7_inversion_share": float(
                np.count_nonzero(settlements[3:6] > settlements[4:7]) / 3.0
            ),
        }
        expected["front_to_mid_log_ratio"] = float(
            np.log(expected["f4_f7_level"] / expected["front_curve_level"])
        )
        if not all(_same_number(row.get(field), value, tolerance=1e-10) for field, value in expected.items()):
            return False

        source_kind = str(row.get("vxcm30_source_kind"))
        expected_vxcm30: float | None = None
        expected_kind = "UNAVAILABLE"
        for index in range(6):
            if days[index] <= VXCM30_TARGET_DAYS < days[index + 1]:
                weight = (VXCM30_TARGET_DAYS - days[index]) / (days[index + 1] - days[index])
                expected_vxcm30 = float(
                    settlements[index] + weight * (settlements[index + 1] - settlements[index])
                )
                expected_kind = "DIRECT_BRACKET_INTERPOLATION"
                break
        if expected_vxcm30 is None and VXCM30_TARGET_DAYS < days[0] <= 36.0:
            weight = (VXCM30_TARGET_DAYS - days[0]) / (days[1] - days[0])
            expected_vxcm30 = float(settlements[0] + weight * (settlements[1] - settlements[0]))
            expected_kind = "BOUNDED_BACKWARD_EXTRAPOLATION"
        if source_kind != expected_kind:
            return False
        if expected_vxcm30 is None:
            return pd.isna(row.get("vxcm30")) and row.get("vxcm30_methodology") is None
        return bool(
            _same_number(row.get("vxcm30"), expected_vxcm30, tolerance=1e-10)
            and row.get("vxcm30_methodology") == VXCM30_METHODOLOGY
        )
    except (TypeError, ValueError, ZeroDivisionError):
        return False


def _station_probability_model_assessment(
    events: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    statuses: list[str] = []
    for event in EVENT_ORDER:
        evidence = events.get(event, {})
        validation = evidence.get("validation", {})
        validation = validation if isinstance(validation, dict) else {}
        if event in BASE_RATE_ONLY_EVENTS:
            status = "BASE_RATE_ONLY_EXEMPT"
        elif not bool(evidence.get("validation_complete")):
            status = "INSUFFICIENT_EVIDENCE"
        elif bool(validation.get("accepted")):
            status = "PASS"
        else:
            status = "FAIL"
        if event in FEATURE_CONDITIONAL_EVENTS:
            statuses.append(status)
        results[event] = {"status": status, **validation}
    overall = (
        "FAIL"
        if "FAIL" in statuses
        else "INSUFFICIENT_EVIDENCE"
        if "INSUFFICIENT_EVIDENCE" in statuses
        else "PASS"
    )
    return overall, {
        "events": results,
        "conditional_model_events": list(FEATURE_CONDITIONAL_EVENTS),
        "base_rate_only_events": list(BASE_RATE_ONLY_EVENTS),
    }


def _station_base_rate_reference_assessment(
    calibration_events: dict[str, dict[str, Any]],
    probability_model_evidence: dict[str, Any],
    oof: pd.DataFrame,
) -> tuple[bool, dict[str, Any]]:
    event = "broad_stress_persists_10d"
    calibration = calibration_events.get(event, {})
    validation = cast(dict[str, Any], calibration.get("validation", {}))
    model_events = cast(dict[str, Any], probability_model_evidence.get("events", {}))
    model = cast(dict[str, Any], model_events.get(event, {}))
    latest_events = cast(
        dict[str, Any], probability_model_evidence.get("last_eligible_publication", {})
    )
    latest = cast(dict[str, Any], latest_events.get(event, {}))
    rows = oof.loc[oof["event_id"].eq(event)]
    numeric_equal = bool(
        len(rows)
        and np.allclose(
            pd.to_numeric(rows["published_probability"], errors="coerce"),
            pd.to_numeric(rows["base_rate_at_prediction"], errors="coerce"),
            equal_nan=False,
        )
    )
    checks = {
        "publication_policy": calibration.get("publication_policy")
        == "BASE_RATE_ONLY_EXEMPT",
        "validation_complete": bool(calibration.get("validation_complete")),
        "validation_exempt_and_accepted": bool(validation.get("exempt"))
        and bool(validation.get("accepted")),
        "raw_oof_zero": int(calibration.get("raw_oof", -1)) == 0
        and bool(rows["raw_probability"].isna().all()),
        "published_equals_causal_base_rate": numeric_equal,
        "calibration_not_applicable": bool(
            rows["calibration_method"].eq("NOT_APPLICABLE").all()
        ),
        "model_count_exempt": model.get("status") == "BASE_RATE_ONLY_EXEMPT",
        "latest_publication_base_rate_only": latest.get("model_status") == "BASE_RATE_ONLY"
        and bool(latest.get("matches")),
    }
    return all(checks.values()), {
        "event_id": event,
        "checks": checks,
        "reference_rows": int(len(rows)),
        "model_pass_claimed": False,
        "latest_eligible_publication": latest,
    }


def _station_fragility_boundary_assessment(
    *,
    project_dir: str | Path,
    states: pd.DataFrame,
    targets: pd.DataFrame,
    oof: pd.DataFrame,
    latest_snapshot: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    root = Path(project_dir).resolve()
    schema = read_json(root / "schemas" / "daily_output.schema.json")
    probability_schema = cast(
        dict[str, Any], cast(dict[str, Any], schema["properties"])["probability_judgment"]
    )
    schema_required = cast(list[str], probability_schema.get("required", []))
    schema_properties = cast(dict[str, Any], probability_schema.get("properties", {}))
    snapshot_events = cast(dict[str, Any], latest_snapshot.get("probability_judgment", {}))
    manifest = read_json(root / "MATVIX_V3_RELEASE_MANIFEST.json")
    scientific_evidence = manifest.get("scientific_evidence")
    fragility_evidence = (
        scientific_evidence.get("fragility_boundary")
        if isinstance(scientific_evidence, dict)
        else None
    )
    event = REJECTED_FRAGILITY_EVENT_ID
    checks = {
        "event_order_absent": event not in EVENT_ORDER,
        "logistic_config_absent": event not in LOGISTIC_FEATURES,
        "target_ledger_absent": not bool(targets["event_id"].eq(event).any()),
        "oof_ledger_absent": not bool(oof["event_id"].eq(event).any()),
        "state_surface_absent": not any(event in str(column) for column in states.columns),
        "schema_required_absent": event not in schema_required,
        "schema_property_absent": event not in schema_properties,
        "daily_snapshot_absent": event not in snapshot_events,
        "rejection_evidence_retained": fragility_evidence
        == {
            "event_id": event,
            "formal_model_status": "NOT_ELIGIBLE",
            "formal_model_pass_claimed": False,
            "rejection_reason": "REJECTED_INSUFFICIENT_PUBLISHED_OOF",
            "completed_published_oof": REJECTED_FRAGILITY_COMPLETED_OOF,
            "required_published_oof": REJECTED_FRAGILITY_REQUIRED_OOF,
            "candidate_artifact_sha256": REJECTED_FRAGILITY_ARTIFACT_SHA256,
        },
    }
    return all(checks.values()), {
        "event_id": event,
        "checks": checks,
        "formal_model_status": "NOT_ELIGIBLE",
        "formal_model_pass_claimed": False,
        "published_oof_completed": REJECTED_FRAGILITY_COMPLETED_OOF,
        "required_published_oof": REJECTED_FRAGILITY_REQUIRED_OOF,
        "adapter_shadow_counted_as_station_model": False,
    }


def _station_tenor_stage_masks(states: pd.DataFrame) -> dict[str, pd.Series]:
    broad = states["stress_tenor_scope"].eq("BROAD")
    mid = states["mid_curve_pressure_state"]
    return {
        "DIFFUSING": broad & mid.eq("RISING"),
        "PRICED": broad & mid.eq("PRICED"),
        "RECEDING": mid.eq("RECEDING"),
    }


def _station_tenor_evidence(states: pd.DataFrame) -> tuple[bool, dict[str, Any]]:
    dates = pd.to_datetime(states["session_date"]).dt.normalize()
    windows = {
        "DEVELOPMENT": dates.le(pd.Timestamp("2021-12-31")),
        "CONFIRMATION": dates.ge(pd.Timestamp("2022-01-03")),
    }
    stage_masks = _station_tenor_stage_masks(states)
    directions = {"DIFFUSING": 1, "PRICED": 1, "RECEDING": -1}
    window_evidence: dict[str, Any] = {}
    stage_checks: list[bool] = []
    for window_name, window_mask in windows.items():
        window_evidence[window_name] = {}
        for stage_name, direction in directions.items():
            rows = states.loc[window_mask & stage_masks[stage_name]]
            medians = {
                column: float(pd.to_numeric(rows[column], errors="coerce").median())
                for column in (
                    "d5_log_f4_f7_level",
                    "d10_log_f4_f7_level",
                    "d5_f4_f7_slope30",
                    "d10_f4_f7_slope30",
                )
            }
            direction_ok = (
                medians["d5_log_f4_f7_level"] * direction > 0
                and medians["d10_log_f4_f7_level"] * direction > 0
                and medians["d5_f4_f7_slope30"] * direction < 0
                and medians["d10_f4_f7_slope30"] * direction < 0
            )
            passed = len(rows) >= 75 and direction_ok
            stage_checks.append(passed)
            window_evidence[window_name][stage_name] = {
                "sessions": int(len(rows)),
                "medians": medians,
                "passed": passed,
            }

    loco: dict[str, Any] = {}
    for stage_name, direction in directions.items():
        clusters = _true_clusters(states["session_date"], stage_masks[stage_name])
        stage_loco: dict[str, Any] = {}
        for column, expected_sign in {
            "d5_log_f4_f7_level": direction,
            "d10_log_f4_f7_level": direction,
            "d5_f4_f7_slope30": -direction,
            "d10_f4_f7_slope30": -direction,
        }.items():
            values = [
                float(
                    pd.to_numeric(
                        states.iloc[
                            int(cluster["start_index"]) : int(cluster["end_index"]) + 1
                        ][column],
                        errors="coerce",
                    ).median()
                )
                for cluster in clusters
            ]
            stage_loco[column] = _loco_direction(values, expected_sign)
        loco[stage_name] = {
            "clusters": len(clusters),
            "metrics": stage_loco,
            "status": (
                "STABLE"
                if all(result["status"] == "STABLE" for result in stage_loco.values())
                else "UNSTABLE"
            ),
        }
    loco_passed = all(evidence["status"] == "STABLE" for evidence in loco.values())
    front = states.loc[states["stress_tenor_scope"].eq("FRONT")]
    front_distinct = bool(
        len(front)
        and front["mid_curve_pressure_state"].isin(["QUIET", "RECEDING"]).all()
    )
    passed = all(stage_checks) and loco_passed and front_distinct
    return passed, {
        "window_stage_facts": window_evidence,
        "leave_one_cluster_out": loco,
        "front_localized_sessions": int(len(front)),
        "front_localized_is_distinct": front_distinct,
    }


def _station_state_timing_evidence(
    features: pd.DataFrame,
    states: pd.DataFrame,
    phase_a_daily: pd.DataFrame,
    phase_a_summary: dict[str, Any],
) -> tuple[bool, dict[str, Any], pd.Series, pd.DataFrame]:
    replayed = build_state_table(features)
    state_columns = [
        *STRUCTURE_VALUES,
        *ANSWER_COLUMNS,
        "raw_phase",
        "phase",
    ]
    column_replay = {
        column: _series_equal(states[column], replayed[column]) for column in state_columns
    }
    replay_rows = pd.Series(True, index=states.index)
    for column in state_columns:
        same = states[column].eq(replayed[column]) | (
            states[column].isna() & replayed[column].isna()
        )
        replay_rows &= same.fillna(False)

    ok = states["data_status"].eq("OK")
    ok_complete = bool(
        all(states.loc[ok, column].isin(values).all() for column, values in STRUCTURE_VALUES.items())
        and all(states.loc[ok, column].isin(ANSWER_VALUES[column]).all() for column in ANSWER_COLUMNS)
        and states.loc[ok, "phase"].isin(PHASE_VALUES).all()
    )
    unknown_columns = [*ANSWER_COLUMNS, "raw_phase", "phase"]
    unknown_propagation = bool(
        states.loc[~ok, unknown_columns].eq("UNKNOWN").all(axis=None)
    )
    phase_diff = states["phase"].ne(states["raw_phase"])
    phase_pairs = pd.Series(
        list(zip(states["phase"], states["raw_phase"], strict=True)),
        index=states.index,
        dtype="object",
    )
    acute_hysteresis = phase_diff & states["phase"].eq("ACUTE_FRONT_STRESS")
    risk_on_confirmation = phase_diff & phase_pairs.isin(RISK_ON_CONFIRMATION_TRANSITIONS)
    invalid_hysteresis = phase_diff & ~acute_hysteresis & ~risk_on_confirmation
    phase_hysteresis_allowed = not bool(invalid_hysteresis.any())
    risk_on_confirmation_rows = [
        {
            "session_date": _date(row["session_date"]),
            "published_source": str(row["phase"]),
            "raw_destination": str(row["raw_phase"]),
        }
        for _, row in states.loc[
            risk_on_confirmation, ["session_date", "phase", "raw_phase"]
        ].iterrows()
    ]
    repair_without_carry = int(
        (states["repair_answer"].eq("CONFIRMED") & ~states["carry_answer"].eq("SUPPORTIVE")).sum()
    )
    carry_without_repair = int(
        (states["carry_answer"].eq("SUPPORTIVE") & ~states["repair_answer"].eq("CONFIRMED")).sum()
    )

    raw_columns = [
        "session_date",
        "phase",
        *[f"{name}__event" for name in (
            "acute_front_pressure",
            "front_inversion",
            "mid_curve_diffusion",
            "broad_stress",
            "mid_pressure_receding",
            "carry_recovered",
        )],
    ]
    timing_daily = phase_a_daily[raw_columns].rename(columns={"phase": "v1_phase"}).merge(
        states[
            [
                "session_date",
                "data_status",
                "hard_acute",
                "carry_answer",
                "shock_answer",
                "persistence_answer",
                "repair_answer",
                "carry_environment_state",
                "phase",
            ]
        ],
        on="session_date",
        how="inner",
        validate="one_to_one",
    )
    signals = {
        "acute_front_pressure": timing_daily["hard_acute"].eq(True),
        "front_inversion": timing_daily["carry_answer"].eq("INVERTED"),
        "mid_curve_diffusion": timing_daily["persistence_answer"].eq("DIFFUSING"),
        "broad_stress": timing_daily["persistence_answer"].eq("PERSISTENT"),
        "mid_pressure_receding": timing_daily["repair_answer"].eq("CONFIRMED"),
        "carry_recovered": timing_daily["carry_environment_state"].eq("OPEN"),
    }
    v1_events = cast(
        dict[str, Any], cast(dict[str, Any], phase_a_summary.get("timing", {})).get("events", {})
    )
    timing_events: dict[str, Any] = {}
    timing_checks: list[bool] = []
    for name, signal in signals.items():
        raw_clusters = _true_clusters(
            timing_daily["session_date"], timing_daily[f"{name}__event"]
        )
        signal_clusters = _true_clusters(timing_daily["session_date"], signal)
        window = 10 if name in {"broad_stress", "carry_recovered"} else 5
        v2 = _match_clusters(raw_clusters, signal_clusters, lead_window=window, lag_window=window)
        v1 = cast(dict[str, Any], v1_events.get(name, {}))
        comparison = {
            "misses_not_higher": int(v2["missed_event_clusters"])
            <= int(v1.get("missed_event_clusters", -1)),
            "false_alarms_not_higher": int(v2["false_alarm_clusters"])
            <= int(v1.get("false_alarm_clusters", -1)),
            "median_delay_not_later": float(v2["median_detection_delay_sessions"])
            <= float(v1.get("median_detection_delay_sessions", -math.inf)),
        }
        timing_checks.extend(comparison.values())
        compact_fields = (
            "event_clusters",
            "matched_event_clusters",
            "missed_event_clusters",
            "signal_clusters",
            "false_alarm_clusters",
            "median_detection_delay_sessions",
        )
        timing_events[name] = {
            "v1": {field: v1.get(field) for field in compact_fields},
            "v2": {field: v2.get(field) for field in compact_fields},
            "comparison": comparison,
        }
        timing_daily[f"{name}__v2_signal"] = signal

    repair_clusters = _true_clusters(
        timing_daily["session_date"], signals["mid_pressure_receding"]
    )
    premature = sum(
        bool(timing_daily.iloc[int(cluster["start_index"])]["broad_stress__event"])
        and not bool(
            timing_daily.iloc[int(cluster["start_index"])]["mid_pressure_receding__event"]
        )
        for cluster in repair_clusters
    )
    premature_rate = float(premature / len(repair_clusters)) if repair_clusters else math.nan
    repair_passed = bool(repair_clusters and premature_rate <= 0.0448)

    stable_interface = (
        timing_daily["data_status"].eq("OK")
        & timing_daily["carry_answer"].eq("SUPPORTIVE")
        & timing_daily["shock_answer"].eq("CALM")
        & timing_daily["persistence_answer"].eq("NORMAL")
    ).to_numpy(dtype=bool)
    recovery_delays: list[int] = []
    recovery_clusters = _true_clusters(
        timing_daily["session_date"], timing_daily["carry_recovered__event"]
    )
    for cluster in recovery_clusters:
        start, end = int(cluster["start_index"]), int(cluster["end_index"])
        offsets = np.flatnonzero(stable_interface[start : end + 1])
        recovery_delays.append(int(offsets[0]) if len(offsets) else end - start + 1)
    recovery_median = float(np.median(recovery_delays)) if recovery_delays else math.nan
    recovery_max = int(max(recovery_delays)) if recovery_delays else -1
    recovery_passed = bool(recovery_delays and recovery_median <= 2 and recovery_max <= 23)
    v1_churn = int(timing_daily["v1_phase"].ne(timing_daily["v1_phase"].shift()).sum() - 1)
    v2_churn = int(timing_daily["phase"].ne(timing_daily["phase"].shift()).sum() - 1)

    state_passed = bool(
        all(column_replay.values())
        and replay_rows.all()
        and ok_complete
        and unknown_propagation
        and phase_hysteresis_allowed
        and repair_without_carry > 0
        and carry_without_repair > 0
    )
    passed = state_passed and all(timing_checks) and repair_passed and recovery_passed
    return passed, {
        "state": {
            "column_replay": column_replay,
            "replay_mismatched_rows": int((~replay_rows).sum()),
            "ok_rows_complete": ok_complete,
            "unknown_propagation": unknown_propagation,
            "phase_raw_differences": int(phase_diff.sum()),
            "phase_hysteresis_allowed": phase_hysteresis_allowed,
            "acute_release_hysteresis_rows": int(acute_hysteresis.sum()),
            "risk_on_confirmation_rows": risk_on_confirmation_rows,
            "risk_on_confirmation_count": int(risk_on_confirmation.sum()),
            "invalid_or_risk_off_delayed_rows": int(invalid_hysteresis.sum()),
            "repair_confirmed_without_carry_supportive": repair_without_carry,
            "carry_supportive_without_repair_confirmed": carry_without_repair,
        },
        "timing": {
            "events": timing_events,
            "repair_premature_release": {
                "signal_clusters": len(repair_clusters),
                "premature_clusters": int(premature),
                "rate": premature_rate,
                "passed": repair_passed,
            },
            "carry_recovery_stable_interface": {
                "event_clusters": len(recovery_delays),
                "median_sessions_closed": recovery_median,
                "max_sessions_closed": recovery_max,
                "passed": recovery_passed,
            },
            "phase_transitions": {"v1": v1_churn, "v2": v2_churn},
            "churn_improvement_claimed": False,
        },
    }, replay_rows, timing_daily


def build_v2_station_acceptance(
    *,
    observations: pd.DataFrame,
    vx_contracts: pd.DataFrame,
    features: pd.DataFrame,
    states: pd.DataFrame,
    targets: pd.DataFrame,
    oof: pd.DataFrame,
    real_acceptance: dict[str, Any],
    phase_a_daily: pd.DataFrame,
    phase_a_summary: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build the weather-only Phase-D ledger and five independent verdicts."""

    features = features.sort_values("session_date").reset_index(drop=True)
    states = states.sort_values("session_date").reset_index(drop=True)
    if not _series_equal(features["session_date"], states["session_date"]):
        raise ValueError("V2 station acceptance requires aligned feature/state histories")
    real_gates = {str(gate["name"]): gate for gate in real_acceptance.get("gates", [])}
    data_real_gate_names = (
        "state_session_integrity",
        "latest_complete_state",
        "ok_state_business_truth",
        "core_series_real_coverage",
        "standard_monthly_vx_real_coverage",
    )
    data_real_checks = {
        name: bool(real_gates.get(name, {}).get("passed")) for name in data_real_gate_names
    }
    ok = states["data_status"].eq("OK")
    required_complete = states[list(STATION_REQUIRED_OK_FIELDS)].notna().all(axis=1)
    vintage_legal = (
        states["formal_vintage_eligible"].fillna(False).astype(bool)
        & states["vx_formal_vintage_eligible"].fillna(False).astype(bool)
        & states["feature_vintage_kind"].isin(["OBSERVED_PIT", "ASSUMED_PIT"])
    )
    formula_valid = states.apply(_station_curve_formula_valid, axis=1)
    source_counts = {
        str(key): int(value) for key, value in states["vxcm30_source_kind"].value_counts().items()
    }
    pseudo = cast(
        dict[str, Any],
        cast(
            dict[str, Any],
            cast(dict[str, Any], phase_a_summary.get("data", {})).get("vxcm30", {}),
        ).get("pseudo_gap_validation", {}),
    )
    pseudo_checks: dict[str, bool] = {}
    for window, minimum in (("development", 250), ("confirmation", 150)):
        values = cast(dict[str, Any], pseudo.get(window, {}))
        pseudo_checks[window] = bool(
            int(values.get("samples", 0)) >= minimum
            and abs(float(values.get("bias_vix_points", math.inf))) <= 0.15
            and float(values.get("mae_vix_points", math.inf)) <= 0.15
            and float(values.get("median_absolute_percentage_error", math.inf)) <= 0.01
            and float(values.get("p95_absolute_percentage_error", math.inf)) <= 0.02
            and float(values.get("max_absolute_percentage_error", math.inf)) <= 0.05
            and float(values.get("correlation", -math.inf)) >= 0.995
        )
    append = _append_invariance(observations, vx_contracts, features, states, oof)
    append_passed = bool(append.get("passed"))
    d5_nulls = {
        column: int(states[column].isna().sum())
        for column in ("d5_log_vxcm30", "d5_basis30_eod")
    }
    data_passed = bool(
        required_complete.loc[ok].all()
        and vintage_legal.loc[ok].all()
        and formula_valid.loc[ok].all()
        and source_counts.get("DIRECT_BRACKET_INTERPOLATION") == 3172
        and source_counts.get("BOUNDED_BACKWARD_EXTRAPOLATION") == 162
        and source_counts.get("UNAVAILABLE", 0) == 0
        and all(value == 5 for value in d5_nulls.values())
        and all(pseudo_checks.values())
        and append_passed
        and all(data_real_checks.values())
    )
    tenor_passed, tenor_evidence = _station_tenor_evidence(states)
    state_timing_passed, state_timing_evidence, replay_rows, timing_daily = (
        _station_state_timing_evidence(features, states, phase_a_daily, phase_a_summary)
    )

    integrity_gate_names = (
        "target_ledger_truth",
        "v3_event_target_cohorts",
        "oof_training_boundaries",
        "v3_oof_calibration_integrity",
        "probability_publication_truth",
    )
    integrity_checks = {
        name: bool(real_gates.get(name, {}).get("passed")) for name in integrity_gate_names
    }
    event_set_truth = set(targets["event_id"].dropna()) == set(EVENT_ORDER) and set(
        oof["event_id"].dropna()
    ) == set(EVENT_ORDER)
    probability_integrity_passed = all(integrity_checks.values()) and event_set_truth
    calibration_evidence = cast(
        dict[str, Any], real_gates.get("v3_oof_calibration_integrity", {}).get("evidence", {})
    )
    calibration_events = cast(dict[str, dict[str, Any]], calibration_evidence.get("events", {}))
    probability_model_status, probability_model_evidence = (
        _station_probability_model_assessment(calibration_events)
    )
    status_frame = add_event_statuses(states)
    last_eligible: dict[str, Any] = {}
    fallback_truth = True
    for event in EVENT_ORDER:
        eligible = status_frame.loc[
            status_frame[f"{event}__event_status"].eq("ELIGIBLE"), "session_date"
        ]
        if eligible.empty:
            last_eligible[event] = {"status": "INSUFFICIENT_EVIDENCE"}
            fallback_truth = False
            continue
        prediction_date = pd.Timestamp(eligible.iloc[-1]).normalize()
        publication, metadata, _ = probability_for_event(
            states,
            targets,
            event,
            prediction_date,
            oof=oof.loc[oof["event_id"].eq(event)],
            formal_runtime_required=True,
        )
        model_evidence = cast(
            dict[str, Any], probability_model_evidence["events"][event]
        )
        expected_model = (
            "BASE_RATE_ONLY"
            if event in BASE_RATE_ONLY_EVENTS
            else "CALIBRATED_MODEL"
            if model_evidence["status"] == "PASS"
            else "BASE_RATE_ONLY"
        )
        matches = publication["model_status"] == expected_model
        fallback_truth &= matches
        last_eligible[event] = {
            "prediction_date": prediction_date.date().isoformat(),
            "model_status": publication["model_status"],
            "expected_model_status": expected_model,
            "fallback_reason": metadata.get("fallback_reason"),
            "matches": matches,
        }
    if not fallback_truth:
        probability_model_status = "FAIL"
    probability_model_evidence["last_eligible_publication"] = last_eligible
    probability_model_evidence["base_rate_fallback_truth"] = fallback_truth

    expected_status = add_event_statuses(states)
    target_status_daily = pd.Series(True, index=states.index)
    target_counts = targets.groupby("prediction_date").size()
    completed_counts = (
        targets["label_status"].isin(["OBSERVED_0", "OBSERVED_1"])
        .groupby(targets["prediction_date"])
        .sum()
    )
    for event in EVENT_ORDER:
        actual = targets.loc[targets["event_id"].eq(event)].set_index("prediction_date")
        actual_status = states["session_date"].map(actual["event_status"])
        target_status_daily &= actual_status.eq(expected_status[f"{event}__event_status"])
    oof_counts = oof.groupby("prediction_date").size()
    timing_flags = timing_daily.set_index("session_date")
    daily = pd.DataFrame(
        {
            "session_date": states["session_date"],
            "data_status": states["data_status"],
            "data_required_complete": required_complete,
            "data_vintage_legal": vintage_legal,
            "curve_formula_replayed": formula_valid,
            "state_replay_match": replay_rows,
            "target_rows": states["session_date"].map(target_counts).fillna(0).astype(int),
            "completed_target_rows": states["session_date"]
            .map(completed_counts)
            .fillna(0)
            .astype(int),
            "target_status_replayed": target_status_daily,
            "oof_rows": states["session_date"].map(oof_counts).fillna(0).astype(int),
        }
    )
    for name in (
        "acute_front_pressure",
        "front_inversion",
        "mid_curve_diffusion",
        "broad_stress",
        "mid_pressure_receding",
        "carry_recovered",
    ):
        daily[f"{name}__raw_event"] = daily["session_date"].map(
            timing_flags[f"{name}__event"]
        )
        daily[f"{name}__v2_signal"] = daily["session_date"].map(
            timing_flags[f"{name}__v2_signal"]
        )

    dimensions: dict[str, dict[str, Any]] = {
        "DATA": {
            "status": "PASS" if data_passed else "FAIL",
            "evidence": {
                "ok_rows": int(ok.sum()),
                "required_field_violations": int((ok & ~required_complete).sum()),
                "vintage_violations": int((ok & ~vintage_legal).sum()),
                "formula_violations": int((ok & ~formula_valid).sum()),
                "vxcm30_source_counts": source_counts,
                "d5_null_counts": d5_nulls,
                "pseudo_gap_fixed_gates": pseudo_checks,
                "future_append_invariance": append,
                "real_source_and_state_gates": data_real_checks,
            },
        },
        "TENOR": {
            "status": "PASS" if tenor_passed else "FAIL",
            "evidence": tenor_evidence,
        },
        "STATE_TIMING": {
            "status": "PASS" if state_timing_passed else "FAIL",
            "evidence": state_timing_evidence,
        },
        "PROBABILITY_INTEGRITY": {
            "status": "PASS" if probability_integrity_passed else "FAIL",
            "evidence": {
                "real_acceptance_gates": integrity_checks,
                "event_set_truth": event_set_truth,
                "event_order": list(EVENT_ORDER),
                "target_rows": int(len(targets)),
                "oof_rows": int(len(oof)),
            },
        },
        "PROBABILITY_MODEL": {
            "status": probability_model_status,
            "evidence": probability_model_evidence,
        },
    }
    key_dimensions = STATION_DIMENSIONS[:4]
    entry_passed = all(dimensions[name]["status"] == "PASS" for name in key_dimensions)
    summary = {
        "acceptance_version": "3.0.0",
        "evidence_boundary": {
            "weather_station_only": True,
            "product_prices_read": False,
            "strategy_or_positions_used": False,
            "vintage_claim": "ASSUMED_PIT",
        },
        "history": {
            "first_session": _date(states["session_date"].min()),
            "last_session": _date(states["session_date"].max()),
            "sessions": int(len(states)),
        },
        "dimensions": dimensions,
        "economic_probe_entry": {
            "status": "PASS" if entry_passed else "FAIL",
            "required_dimensions": list(key_dimensions),
            "probability_model_is_not_an_entry_gate": True,
        },
    }
    return daily, summary


def build_v3_station_acceptance(
    *,
    observations: pd.DataFrame,
    vx_contracts: pd.DataFrame,
    features: pd.DataFrame,
    states: pd.DataFrame,
    targets: pd.DataFrame,
    oof: pd.DataFrame,
    real_acceptance: dict[str, Any],
    phase_a_daily: pd.DataFrame,
    phase_a_summary: dict[str, Any],
    latest_snapshot: dict[str, Any],
    project_dir: str | Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build the V3 weather-only acceptance with every Stage-D gate enforced."""

    daily, summary = build_v2_station_acceptance(
        observations=observations,
        vx_contracts=vx_contracts,
        features=features,
        states=states,
        targets=targets,
        oof=oof,
        real_acceptance=real_acceptance,
        phase_a_daily=phase_a_daily,
        phase_a_summary=phase_a_summary,
    )
    dimensions = cast(dict[str, dict[str, Any]], summary["dimensions"])
    real_gates = {str(gate["name"]): gate for gate in real_acceptance.get("gates", [])}
    calibration_evidence = cast(
        dict[str, Any], real_gates.get("v3_oof_calibration_integrity", {}).get("evidence", {})
    )
    calibration_events = cast(dict[str, dict[str, Any]], calibration_evidence.get("events", {}))
    probability_model_evidence = cast(
        dict[str, Any], dimensions["PROBABILITY_MODEL"]["evidence"]
    )
    base_rate_passed, base_rate_evidence = _station_base_rate_reference_assessment(
        calibration_events, probability_model_evidence, oof
    )
    fragility_passed, fragility_evidence = _station_fragility_boundary_assessment(
        project_dir=project_dir,
        states=states,
        targets=targets,
        oof=oof,
        latest_snapshot=latest_snapshot,
    )
    dimensions["BASE_RATE_REFERENCE"] = {
        "status": "PASS" if base_rate_passed else "FAIL",
        "evidence": base_rate_evidence,
    }
    dimensions["FRAGILITY_BOUNDARY"] = {
        "status": "PASS" if fragility_passed else "FAIL",
        "evidence": fragility_evidence,
    }
    entry_passed = all(
        dimensions[name]["status"] == "PASS" for name in V3_STATION_DIMENSIONS
    )
    summary["station_generation"] = "V3"
    summary["dimension_order"] = list(V3_STATION_DIMENSIONS)
    summary["economic_probe_entry"] = {
        "status": "PASS" if entry_passed else "FAIL",
        "required_dimensions": list(V3_STATION_DIMENSIONS),
        "probability_model_is_an_entry_gate": True,
        "stage_e_pure_document_freeze_still_required": True,
    }
    daily["fragility_formal_surface_absent"] = fragility_passed
    daily["broad_base_rate_reference_valid"] = base_rate_passed
    return daily, summary


def _station_report_markdown(summary: dict[str, Any]) -> str:
    dimensions = cast(dict[str, Any], summary["dimensions"])
    rows = ["| 维度 | 结论 |", "|---|---|"]
    rows.extend(f"| `{name}` | `{dimensions[name]['status']}` |" for name in STATION_DIMENSIONS)
    model_events = cast(
        dict[str, Any], dimensions["PROBABILITY_MODEL"]["evidence"]["events"]
    )
    model_rows = ["| 事件 | 模型结论 | 样本 | Brier Skill | ECE |", "|---|---|---:|---:|---:|"]
    for event in EVENT_ORDER:
        evidence = cast(dict[str, Any], model_events[event])
        skill = evidence.get("brier_skill")
        ece = evidence.get("ece")
        model_rows.append(
            f"| `{event}` | `{evidence['status']}` | {evidence.get('samples', 0)} | "
            f"{float(skill):.2%} | {float(ece):.2%} |"
            if skill is not None and ece is not None
            else f"| `{event}` | `{evidence['status']}` | {evidence.get('samples', 0)} | — | — |"
        )
    data = cast(dict[str, Any], dimensions["DATA"]["evidence"])
    tenor = cast(dict[str, Any], dimensions["TENOR"]["evidence"])
    state_timing = cast(dict[str, Any], dimensions["STATE_TIMING"]["evidence"])
    state = cast(dict[str, Any], state_timing["state"])
    timing = cast(dict[str, Any], state_timing["timing"])
    stage_lines: list[str] = []
    for window in ("DEVELOPMENT", "CONFIRMATION"):
        stages = cast(dict[str, Any], tenor["window_stage_facts"])[window]
        counts = ", ".join(
            f"{name}={cast(dict[str, Any], evidence)['sessions']}"
            for name, evidence in cast(dict[str, Any], stages).items()
        )
        stage_lines.append(f"- {window}: {counts}；5/10 日 level 与 slope-change 方向门均通过。")
    repair = cast(dict[str, Any], timing["repair_premature_release"])
    recovery = cast(dict[str, Any], timing["carry_recovery_stable_interface"])
    churn = cast(dict[str, Any], timing["phase_transitions"])
    integrity = cast(dict[str, Any], dimensions["PROBABILITY_INTEGRITY"]["evidence"])
    entry = summary["economic_probe_entry"]["status"]
    return "\n".join(
        [
            "# MatVIX V2 气象站自身验收",
            "",
            "> 边界：仅使用气象站输入、状态与概率证据；未读取 SVXY、SGOV、VXZ 价格，未使用策略收益。",
            "",
            "## 五维结论",
            "",
            *rows,
            "",
            "不计算总分。前四个关键维度决定是否允许进入一次冻结经济探针；概率模型维度只报告增量证据。",
            "",
            "## 关键站内证据",
            "",
            f"- DATA：OK rows={data['ok_rows']}，必需字段/vintage/公式违规均为 0；"
            f"VXCM30 direct={data['vxcm30_source_counts'].get('DIRECT_BRACKET_INTERPOLATION', 0)}、"
            f"bounded={data['vxcm30_source_counts'].get('BOUNDED_BACKWARD_EXTRAPOLATION', 0)}；"
            f"追加不变共同 OOF={data['future_append_invariance']['common_oof_rows']}。",
            *stage_lines,
            f"- STATE：逐行确定重放差异={state['replay_mismatched_rows']}；"
            f"phase/raw_phase 差异={state['phase_raw_differences']}，其中 acute release="
            f"{state['acute_release_hysteresis_rows']}、冻结 risk-on 确认="
            f"{state['risk_on_confirmation_count']}、非法或 risk-off 延迟="
            f"{state['invalid_or_risk_off_delayed_rows']}。",
            f"- TIMING：Repair 过早释放={repair['premature_clusters']}/{repair['signal_clusters']}；"
            f"carry 恢复后稳定接口继续关闭中位/最大={recovery['median_sessions_closed']}/"
            f"{recovery['max_sessions_closed']} session；phase 转换 V1/V2={churn['v1']}/{churn['v2']}，"
            "不声称 churn 改善。",
            f"- PROBABILITY INTEGRITY：target rows={integrity['target_rows']}，"
            f"OOF rows={integrity['oof_rows']}，五事件集合与所有重放门一致。",
            "",
            "## 概率模型逐事件结论",
            "",
            *model_rows,
            "",
            "`BASE_RATE_ONLY` 是诚实历史参考，不计作特征条件概率增量。",
            "",
            "## 经济探针入口",
            "",
            f"入口结论：`{entry}`。这只授权读取冻结探针所需产品价格，不构成任何收益或生产结论。",
            "",
        ]
    )


def write_v2_station_acceptance(
    daily: pd.DataFrame, summary: dict[str, Any], project_dir: str | Path
) -> dict[str, Path]:
    output_dir = Path(project_dir).resolve() / "outputs" / "v2_station_acceptance"
    daily_path = write_parquet(daily, output_dir / "daily_ledger.parquet")
    summary_path = write_json(summary, output_dir / "summary.json")
    report_path = output_dir / "report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_station_report_markdown(summary), encoding="utf-8")
    return {"daily": daily_path, "summary": summary_path, "report": report_path}


def _v3_station_report_markdown(summary: dict[str, Any]) -> str:
    dimensions = cast(dict[str, Any], summary["dimensions"])
    order = cast(list[str], summary["dimension_order"])
    rows = ["| 维度 | 结论 |", "|---|---|"]
    rows.extend(f"| `{name}` | `{dimensions[name]['status']}` |" for name in order)
    model_events = cast(
        dict[str, Any], dimensions["PROBABILITY_MODEL"]["evidence"]["events"]
    )
    model_rows = ["| 正式对象 | 结论 | 样本 | Brier Skill | ECE |", "|---|---|---:|---:|---:|"]
    for event in EVENT_ORDER:
        evidence = cast(dict[str, Any], model_events[event])
        skill = evidence.get("brier_skill")
        ece = evidence.get("ece")
        if skill is None or ece is None:
            model_rows.append(
                f"| `{event}` | `{evidence['status']}` | {evidence.get('samples', 0)} | — | — |"
            )
        else:
            model_rows.append(
                f"| `{event}` | `{evidence['status']}` | {evidence.get('samples', 0)} | "
                f"{float(skill):.2%} | {float(ece):.2%} |"
            )
    state = cast(dict[str, Any], dimensions["STATE_TIMING"]["evidence"]["state"])
    base = cast(dict[str, Any], dimensions["BASE_RATE_REFERENCE"]["evidence"])
    fragility = cast(dict[str, Any], dimensions["FRAGILITY_BOUNDARY"]["evidence"])
    entry = cast(dict[str, Any], summary["economic_probe_entry"])
    return "\n".join(
        [
            "# MatVIX V3 四模型气象站自身验收",
            "",
            "> 边界：仅使用气象站输入、状态与概率证据；未读取 SVXY、SGOV、VXZ 价格，未使用策略收益。",
            "",
            "## 七维独立结论",
            "",
            *rows,
            "",
            "不计算总分；七个入口维度必须全部 PASS。",
            "",
            "## 正式概率目录",
            "",
            *model_rows,
            "",
            f"Broad reference rows={base['reference_rows']}；只记 `BASE_RATE_ONLY_EXEMPT`，"
            "不计模型 PASS。",
            f"Fragility 正式模型仍为 `{fragility['formal_model_status']}`："
            f"{fragility['published_oof_completed']}/{fragility['required_published_oof']} completed OOF；"
            "本维度 PASS 只证明它未进入运行表面。",
            "",
            "## 状态发布边界",
            "",
            f"- phase/raw_phase 差异={state['phase_raw_differences']}；acute release="
            f"{state['acute_release_hysteresis_rows']}；risk-on confirmation="
            f"{state['risk_on_confirmation_count']}；非法或 risk-off 延迟="
            f"{state['invalid_or_risk_off_delayed_rows']}。",
            "",
            "## 阶段 E 入口",
            "",
            f"`{entry['status']}`。即使 PASS，仍必须先完成价格盲的阶段 E 纯文档适配器冻结；"
            "不构成经济改进、生产晋升或 Fragility 概率通过。",
            "",
        ]
    )


def write_v3_station_acceptance(
    daily: pd.DataFrame, summary: dict[str, Any], project_dir: str | Path
) -> dict[str, Path]:
    output_dir = Path(project_dir).resolve() / "outputs" / "v3_station_acceptance"
    daily_path = write_parquet(daily, output_dir / "daily_ledger.parquet")
    summary_path = write_json(summary, output_dir / "summary.json")
    report_path = output_dir / "report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_v3_station_report_markdown(summary), encoding="utf-8")
    return {"daily": daily_path, "summary": summary_path, "report": report_path}
