from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from conftest import base_state_frame

from matvix.calendar import add_sessions, decision_as_of
from matvix.constants import EVENT_HORIZONS, EVENT_ORDER
from matvix.daily_update import with_snapshot_publication_binding
from matvix.pipeline import ProjectPaths
from matvix.probability.targets import build_target_ledger, event_status
from matvix.prospective import (
    ACTIVATION_TAG,
    PROSPECTIVE_SCHEMA_VERSION,
    SCIENTIFIC_COHORT_ID,
    ProspectiveConflictError,
    binding_for_file,
    build_prediction_record,
    outcome_record_path,
    read_outcome_record,
    write_prediction_record,
)
from matvix.prospective_resolver import resolve_due_outcomes
from matvix.storage import write_json, write_parquet

RELEASE_ID = "git:" + "c" * 40


def _published_event(row: pd.Series, event_id: str, session: str) -> dict[str, object]:
    status = event_status(row, event_id)
    if status != "ELIGIBLE":
        return {
            "event_status": status,
            "model_status": "NOT_RUN",
            "probability_kind": None,
            "probability": None,
            "base_rate": None,
            "valid_through_session": None,
        }
    return {
        "event_status": status,
        "model_status": "CALIBRATED_MODEL",
        "probability_kind": "FEATURE_CONDITIONAL",
        "probability": 0.3,
        "base_rate": 0.2,
        "valid_through_session": add_sessions(
            session, EVENT_HORIZONS[event_id]
        ).date().isoformat(),
    }


def _prospective_fixture(root: Path, states: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    paths = ProjectPaths(root)
    session = pd.Timestamp(states.iloc[0]["session_date"]).date().isoformat()
    targets = build_target_ledger(states)
    write_parquet(states, paths.states)
    write_parquet(targets, paths.targets)
    events = {
        event_id: _published_event(states.iloc[0], event_id, session)
        for event_id in EVENT_ORDER
    }
    snapshot = {
        "session_date": session,
        "decision_as_of": decision_as_of(session).isoformat(),
        "data_status": "OK",
        "probability_judgment": events,
    }
    snapshot_path = paths.daily_output_dir / f"{session}.json"
    write_json(snapshot, snapshot_path)
    metadata = {
        event_id: (
            {
                "publication_method": "ROLLING_INTERCEPT_252",
                "candidate_probability": 0.31,
            }
            if events[event_id]["event_status"] == "ELIGIBLE"
            else {}
        )
        for event_id in EVENT_ORDER
    }
    captured_at = datetime(2024, 1, 3, 14, 20, tzinfo=UTC)
    prediction = build_prediction_record(
        snapshot=snapshot,
        probability_metadata=metadata,
        snapshot_binding=binding_for_file(root, snapshot_path).as_dict(),
        captured_at=captured_at,
        runtime_release_id=RELEASE_ID,
    )
    prediction_write = write_prediction_record(root, prediction)
    receipt = with_snapshot_publication_binding(
        {
            "session_date": session,
            "passed": True,
            "prospective_evidence": {
                "schema_version": PROSPECTIVE_SCHEMA_VERSION,
                "status": "LOCAL_CAPTURED",
                "scientific_cohort_id": SCIENTIFIC_COHORT_ID,
                "activation_tag": ACTIVATION_TAG,
                "activation_commit": "b" * 40,
                "runtime_release_id": RELEASE_ID,
                "captured_at": captured_at.isoformat(),
                "prediction": prediction_write.binding.as_dict(),
                "capture_error": None,
            },
        },
        snapshot_path,
    )
    receipt_path = root / "artifacts" / "acceptance" / f"real_acceptance_{session}.json"
    write_json(receipt, receipt_path)
    return session, targets


def test_resolver_waits_until_due_then_appends_exact_outcomes_idempotently(
    tmp_path: Path,
) -> None:
    states = base_state_frame(12)
    states.loc[2, "hard_acute"] = True
    session, _ = _prospective_fixture(tmp_path, states)
    outcome_at = decision_as_of(add_sessions(session, 5))

    pending = resolve_due_outcomes(
        tmp_path,
        now=outcome_at - timedelta(seconds=1),
        resolver_release_id=RELEASE_ID,
    )
    assert pending.checked_predictions == 1
    assert pending.eligible_events == 3
    assert pending.due_events == 0
    assert pending.pending_events == 3
    assert pending.created_outcomes == 0

    resolved = resolve_due_outcomes(
        tmp_path,
        now=outcome_at,
        resolver_release_id=RELEASE_ID,
    )
    assert resolved.due_events == 3
    assert resolved.pending_events == 0
    assert resolved.created_outcomes == 3
    acute, _ = read_outcome_record(tmp_path, session, "acute_front_stress_5d")
    assert acute["label"] == 1
    assert acute["first_event_session"] == pd.Timestamp(
        states.loc[2, "session_date"]
    ).date().isoformat()
    assert acute["resolved_late"] is False

    repeated = resolve_due_outcomes(
        tmp_path,
        now=outcome_at + timedelta(days=1),
        resolver_release_id=RELEASE_ID,
    )
    assert repeated.created_outcomes == 0
    assert repeated.existing_outcomes == 3
    unchanged, _ = read_outcome_record(tmp_path, session, "acute_front_stress_5d")
    assert unchanged == acute


def test_due_but_censored_outcomes_remain_pending_without_backfill(tmp_path: Path) -> None:
    states = base_state_frame(4)
    session, _ = _prospective_fixture(tmp_path, states)

    summary = resolve_due_outcomes(
        tmp_path,
        now=decision_as_of(add_sessions(session, 10)) + timedelta(days=30),
        resolver_release_id=RELEASE_ID,
    )

    assert summary.eligible_events == 3
    assert summary.due_events == 3
    assert summary.pending_events == 3
    assert summary.created_outcomes == 0
    assert not outcome_record_path(tmp_path, session, "acute_front_stress_5d").exists()


def test_delayed_resolution_preserves_schedule_and_marks_late(tmp_path: Path) -> None:
    states = base_state_frame(12)
    states.loc[2, "hard_acute"] = True
    session, _ = _prospective_fixture(tmp_path, states)
    outcome_at = decision_as_of(add_sessions(session, 5))

    summary = resolve_due_outcomes(
        tmp_path,
        now=outcome_at + timedelta(days=2),
        resolver_release_id=RELEASE_ID,
    )

    assert summary.created_outcomes == 3
    outcome, _ = read_outcome_record(tmp_path, session, "acute_front_stress_5d")
    assert outcome["outcome_available_at"] == outcome_at.isoformat()
    assert outcome["resolved_at"] == (outcome_at + timedelta(days=2)).isoformat()
    assert outcome["resolved_late"] is True


def test_target_revision_that_changes_a_frozen_label_is_an_audit_stop(
    tmp_path: Path,
) -> None:
    states = base_state_frame(12)
    states.loc[2, "hard_acute"] = True
    session, targets = _prospective_fixture(tmp_path, states)
    outcome_at = decision_as_of(add_sessions(session, 5))
    resolve_due_outcomes(tmp_path, now=outcome_at, resolver_release_id=RELEASE_ID)

    mask = targets["event_id"].eq("acute_front_stress_5d") & pd.to_datetime(
        targets["prediction_date"]
    ).dt.normalize().eq(pd.Timestamp(session))
    targets.loc[mask, "label"] = 0
    targets.loc[mask, "label_status"] = "OBSERVED_0"
    write_parquet(targets, ProjectPaths(tmp_path).targets)

    with pytest.raises(ProspectiveConflictError, match="frozen predicate"):
        resolve_due_outcomes(
            tmp_path,
            now=outcome_at + timedelta(days=1),
            resolver_release_id=RELEASE_ID,
        )
