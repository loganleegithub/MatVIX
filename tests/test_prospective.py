from __future__ import annotations

import json
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from matvix.calendar import add_sessions, decision_as_of
from matvix.constants import EVENT_HORIZONS, EVENT_ORDER
from matvix.prospective import (
    ACTIVATION_TAG,
    PROSPECTIVE_SCHEMA_VERSION,
    SCIENTIFIC_COHORT_ID,
    ProspectiveConflictError,
    ProspectiveCorruptionError,
    ProspectiveValidationError,
    binding_for_file,
    build_prediction_record,
    outcome_record_path,
    prediction_record_path,
    validate_outcome_record,
    validate_prediction_record,
    write_outcome_record,
    write_prediction_record,
)
from matvix.storage import write_json

SESSION = "2025-01-02"
RELEASE_ID = "git:" + "a" * 40


def _snapshot_event(event_id: str) -> dict[str, object]:
    valid = add_sessions(SESSION, EVENT_HORIZONS[event_id]).date().isoformat()
    if event_id == "broad_stress_persists_10d":
        model_status = "BASE_RATE_ONLY"
        kind = "HISTORICAL_REFERENCE"
        probability = 0.2
        base_rate = 0.2
    else:
        model_status = "CALIBRATED_MODEL"
        kind = "FEATURE_CONDITIONAL"
        probability = 0.3
        base_rate = 0.2
    return {
        "event_status": "ELIGIBLE",
        "model_status": model_status,
        "probability_kind": kind,
        "probability": probability,
        "base_rate": base_rate,
        "valid_through_session": valid,
    }


def _prediction(root: Path) -> dict[str, object]:
    snapshot = {
        "session_date": SESSION,
        "decision_as_of": decision_as_of(SESSION).isoformat(),
        "probability_judgment": {
            event_id: _snapshot_event(event_id) for event_id in EVENT_ORDER
        },
    }
    snapshot_path = root / "outputs" / "daily" / f"{SESSION}.json"
    write_json(snapshot, snapshot_path)
    metadata = {
        event_id: {
            "publication_method": "ROLLING_INTERCEPT_252",
            "candidate_probability": 0.31,
        }
        for event_id in EVENT_ORDER
    }
    return build_prediction_record(
        snapshot=snapshot,
        probability_metadata=metadata,
        snapshot_binding=binding_for_file(root, snapshot_path).as_dict(),
        captured_at=datetime(2025, 1, 3, 14, 30, tzinfo=UTC),
        runtime_release_id=RELEASE_ID,
    )


def _outcome(root: Path, prediction: dict[str, object], *, label: int = 1) -> dict[str, object]:
    prediction_result = write_prediction_record(root, prediction)
    target_path = root / "data" / "probability" / "target_ledger.parquet"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(b"frozen-target-ledger")
    event_id = "acute_front_stress_5d"
    valid = add_sessions(SESSION, EVENT_HORIZONS[event_id]).date().isoformat()
    outcome_at = decision_as_of(valid)
    return {
        "schema_version": PROSPECTIVE_SCHEMA_VERSION,
        "record_type": "OUTCOME_RESOLVED",
        "scientific_cohort_id": SCIENTIFIC_COHORT_ID,
        "activation_tag": ACTIVATION_TAG,
        "session_date": SESSION,
        "event_id": event_id,
        "horizon_sessions": EVENT_HORIZONS[event_id],
        "valid_through_session": valid,
        "outcome_available_at": outcome_at.isoformat(),
        "resolved_at": (outcome_at + timedelta(days=1)).isoformat(),
        "resolved_late": True,
        "label": label,
        "label_status": f"OBSERVED_{label}",
        "first_event_session": add_sessions(SESSION, 2).date().isoformat()
        if label
        else None,
        "prediction": prediction_result.binding.as_dict(),
        "target_ledger": binding_for_file(root, target_path).as_dict(),
        "resolver_release_id": RELEASE_ID,
    }


def test_prediction_builder_separates_published_candidate_and_broad_reference(
    tmp_path: Path,
) -> None:
    record = _prediction(tmp_path)

    validate_prediction_record(record)
    acute = record["events"]["acute_front_stress_5d"]
    broad = record["events"]["broad_stress_persists_10d"]
    assert acute["published_probability"] == 0.3
    assert acute["candidate_probability"] == 0.31
    assert broad["published_probability"] == broad["causal_base_rate"] == 0.2
    assert broad["candidate_probability"] is None
    encoded = json.dumps(record, sort_keys=True)
    assert all(name not in encoded for name in ("SVXY", "SGOV", "VXZ"))


def test_prediction_exclusive_write_is_read_only_hash_bound_and_idempotent(
    tmp_path: Path,
) -> None:
    record = _prediction(tmp_path)

    first = write_prediction_record(tmp_path, record)
    second = write_prediction_record(tmp_path, record)

    assert first.created is True
    assert second.created is False
    assert first.binding == second.binding == binding_for_file(tmp_path, first.path)
    assert first.path == prediction_record_path(tmp_path, SESSION)
    assert stat.S_IMODE(first.path.stat().st_mode) == 0o444
    assert first.binding.relative_path == f"data/prospective/core/predictions/{SESSION}.json"


def test_prediction_conflict_preserves_original_bytes(tmp_path: Path) -> None:
    record = _prediction(tmp_path)
    result = write_prediction_record(tmp_path, record)
    original = result.path.read_bytes()
    conflicting = json.loads(json.dumps(record))
    conflicting["events"]["acute_front_stress_5d"]["candidate_probability"] = 0.32

    with pytest.raises(ProspectiveConflictError, match="existing bytes preserved"):
        write_prediction_record(tmp_path, conflicting)

    assert result.path.read_bytes() == original


def test_prediction_existing_mutable_file_is_corruption(tmp_path: Path) -> None:
    record = _prediction(tmp_path)
    result = write_prediction_record(tmp_path, record)
    result.path.chmod(0o644)

    with pytest.raises(ProspectiveCorruptionError, match="not read-only"):
        write_prediction_record(tmp_path, record)


def test_invalid_prediction_never_creates_evidence(tmp_path: Path) -> None:
    record = _prediction(tmp_path)
    record["events"]["acute_front_stress_5d"]["horizon_sessions"] = 10

    with pytest.raises(ProspectiveValidationError, match="horizon mismatch"):
        write_prediction_record(tmp_path, record)

    assert not prediction_record_path(tmp_path, SESSION).exists()


def test_outcome_schema_and_exclusive_writer(tmp_path: Path) -> None:
    prediction = _prediction(tmp_path)
    outcome = _outcome(tmp_path, prediction)

    validate_outcome_record(outcome)
    first = write_outcome_record(tmp_path, outcome)
    second = write_outcome_record(tmp_path, outcome)

    assert first.created is True
    assert second.created is False
    assert first.binding == binding_for_file(tmp_path, first.path)
    assert first.path == outcome_record_path(
        tmp_path, SESSION, "acute_front_stress_5d"
    )
    assert stat.S_IMODE(first.path.stat().st_mode) == 0o444


def test_outcome_rejects_inconsistent_label_and_late_semantics(tmp_path: Path) -> None:
    prediction = _prediction(tmp_path)
    outcome = _outcome(tmp_path, prediction, label=0)
    outcome["first_event_session"] = add_sessions(SESSION, 1).date().isoformat()

    with pytest.raises(ProspectiveValidationError, match="first-event/label mismatch"):
        validate_outcome_record(outcome)

    outcome["first_event_session"] = None
    outcome["resolved_late"] = False
    with pytest.raises(ProspectiveValidationError, match="resolved_late mismatch"):
        validate_outcome_record(outcome)
