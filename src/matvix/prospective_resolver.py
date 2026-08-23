from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd

from matvix.constants import EVENT_HORIZONS, EVENT_ORDER
from matvix.probability.targets import resolve_event_window
from matvix.prospective import (
    ACTIVATION_TAG,
    PROSPECTIVE_SCHEMA_VERSION,
    SCIENTIFIC_COHORT_ID,
    EvidenceBinding,
    ProspectiveConflictError,
    ProspectiveCorruptionError,
    ProspectiveEvidenceError,
    ProspectiveValidationError,
    activation_identity,
    binding_for_file,
    outcome_record_path,
    read_outcome_record,
    read_prediction_record,
    validate_receipt_evidence,
    write_outcome_record,
)
from matvix.storage import read_json, read_parquet

SNAPSHOT_BINDING_VERSION = "SNAPSHOT_SHA256_V1"


@dataclass(frozen=True)
class OutcomeResolutionSummary:
    status: str
    checked_predictions: int
    eligible_events: int
    due_events: int
    pending_events: int
    created_outcomes: int
    existing_outcomes: int
    skipped_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _BoundPrediction:
    session_date: str
    record: dict[str, Any]
    binding: EvidenceBinding


def _content_sha256(path: Path) -> tuple[str, int]:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ProspectiveCorruptionError(f"accepted snapshot is unreadable: {path}") from exc
    return "sha256:" + hashlib.sha256(content).hexdigest(), len(content)


def _receipt_bound_predictions(project_dir: Path) -> list[_BoundPrediction]:
    receipt_dir = project_dir / "artifacts" / "acceptance"
    if not receipt_dir.is_dir():
        return []
    result: list[_BoundPrediction] = []
    for receipt_path in sorted(receipt_dir.glob("real_acceptance_*.json")):
        try:
            receipt = read_json(receipt_path)
        except (OSError, ValueError) as exc:
            raise ProspectiveCorruptionError(f"acceptance receipt is unreadable: {receipt_path}") from exc
        session = receipt.get("session_date")
        if not isinstance(session, str) or receipt_path.name != f"real_acceptance_{session}.json":
            continue
        if receipt.get("passed") is not True:
            continue
        prospective = receipt.get("prospective_evidence")
        if not isinstance(prospective, Mapping):
            continue
        if prospective.get("status") != "LOCAL_CAPTURED":
            continue
        snapshot_path = project_dir / "outputs" / "daily" / f"{session}.json"
        try:
            snapshot = read_json(snapshot_path)
        except (OSError, ValueError) as exc:
            raise ProspectiveCorruptionError(
                f"receipt-bound snapshot is unreadable: {snapshot_path}"
            ) from exc
        if snapshot.get("session_date") != session or snapshot.get("data_status") != "OK":
            raise ProspectiveCorruptionError(f"receipt-bound snapshot identity is invalid: {session}")
        snapshot_sha256, snapshot_size = _content_sha256(snapshot_path)
        snapshot_binding = {
            "binding_version": SNAPSHOT_BINDING_VERSION,
            "session_date": session,
            "snapshot_sha256": snapshot_sha256,
            "snapshot_size": snapshot_size,
        }
        if receipt.get("publication_binding") != snapshot_binding:
            raise ProspectiveCorruptionError(f"receipt snapshot binding mismatch: {session}")
        if receipt_path.stat().st_mtime_ns < snapshot_path.stat().st_mtime_ns:
            raise ProspectiveCorruptionError(f"receipt was not published after snapshot: {session}")
        try:
            validate_receipt_evidence(
                project_dir,
                session,
                prospective,
                snapshot_binding=snapshot_binding,
            )
        except ProspectiveEvidenceError as exc:
            raise ProspectiveCorruptionError(
                f"receipt prediction binding mismatch: {session}"
            ) from exc
        record, binding = read_prediction_record(project_dir, session)
        result.append(_BoundPrediction(session, record, binding))
    return result


def _target_row(targets: pd.DataFrame, session: str, event_id: str) -> pd.Series | None:
    if targets.empty or not {"prediction_date", "event_id"}.issubset(targets.columns):
        return None
    matching = targets.loc[
        pd.to_datetime(targets["prediction_date"]).dt.normalize().eq(pd.Timestamp(session))
        & targets["event_id"].eq(event_id)
    ]
    if len(matching) > 1:
        raise ProspectiveConflictError(f"duplicate target rows: {session}/{event_id}")
    return None if matching.empty else matching.iloc[0]


def _timestamp_iso(value: object, *, field: str) -> str:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ProspectiveValidationError(f"target {field} is invalid") from exc
    if pd.isna(timestamp) or timestamp.tzinfo is None:
        raise ProspectiveValidationError(f"target {field} must be timezone-aware")
    return str(timestamp.isoformat())


def _date_iso(value: object, *, field: str) -> str:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ProspectiveValidationError(f"target {field} is invalid") from exc
    if pd.isna(timestamp):
        raise ProspectiveValidationError(f"target {field} is missing")
    return str(timestamp.date().isoformat())


def _assert_existing_outcome(
    existing: Mapping[str, Any], expected: Mapping[str, Any]
) -> None:
    immutable_semantics = {
        "schema_version",
        "record_type",
        "scientific_cohort_id",
        "activation_tag",
        "session_date",
        "event_id",
        "horizon_sessions",
        "valid_through_session",
        "outcome_available_at",
        "label",
        "label_status",
        "first_event_session",
        "prediction",
    }
    differences = [
        field for field in sorted(immutable_semantics) if existing.get(field) != expected.get(field)
    ]
    if differences:
        raise ProspectiveConflictError(
            "existing outcome conflicts with current frozen resolution: " + ",".join(differences)
        )


def resolve_due_outcomes(
    project_dir: str | Path,
    *,
    now: datetime,
    resolver_release_id: str | None = None,
) -> OutcomeResolutionSummary:
    """Append every causally mature receipt-bound outcome exactly once."""

    if now.tzinfo is None:
        raise ProspectiveValidationError("resolver now must be timezone-aware")
    root = Path(project_dir).resolve()
    if resolver_release_id is None:
        identity = activation_identity(root)
        if not identity.activated:
            return OutcomeResolutionSummary("PRE_ACTIVATION", 0, 0, 0, 0, 0, 0, identity.reason)
        if not identity.capture_ready or identity.runtime_release_id is None:
            return OutcomeResolutionSummary("DEGRADED", 0, 0, 0, 0, 0, 0, identity.reason)
        resolver_release_id = identity.runtime_release_id
    predictions = _receipt_bound_predictions(root)
    if not predictions:
        return OutcomeResolutionSummary("CURRENT", 0, 0, 0, 0, 0, 0)

    state_path = root / "data" / "processed" / "states.parquet"
    target_path = root / "data" / "probability" / "target_ledger.parquet"
    try:
        states = read_parquet(state_path)
        targets = read_parquet(target_path)
        target_binding = binding_for_file(root, target_path)
    except (OSError, ValueError) as exc:
        raise ProspectiveCorruptionError("prospective resolver inputs are unavailable") from exc

    eligible_events = 0
    due_events = 0
    pending_events = 0
    created_outcomes = 0
    existing_outcomes = 0
    for prediction in predictions:
        events = cast(Mapping[str, Mapping[str, Any]], prediction.record["events"])
        for event_id in EVENT_ORDER:
            event = events[event_id]
            if event["event_status"] != "ELIGIBLE":
                continue
            eligible_events += 1
            outcome_at = datetime.fromisoformat(str(event["outcome_available_at"]))
            if now < outcome_at:
                pending_events += 1
                continue
            due_events += 1
            target = _target_row(targets, prediction.session_date, event_id)
            if target is None or target.get("label_status") not in {"OBSERVED_0", "OBSERVED_1"}:
                pending_events += 1
                continue
            if str(target.get("event_status")) != "ELIGIBLE":
                raise ProspectiveConflictError(
                    f"target eligibility conflicts with prediction: {prediction.session_date}/{event_id}"
                )
            horizon = int(target["horizon_sessions"])
            valid_through = _date_iso(target["valid_through_session"], field="valid_through_session")
            available_at = _timestamp_iso(target["outcome_available_at"], field="outcome_available_at")
            if (
                horizon != EVENT_HORIZONS[event_id]
                or horizon != event["horizon_sessions"]
                or valid_through != event["valid_through_session"]
                or available_at != event["outcome_available_at"]
            ):
                raise ProspectiveConflictError(
                    f"target schedule conflicts with prediction: {prediction.session_date}/{event_id}"
                )
            window = resolve_event_window(states, prediction.session_date, event_id)
            if window is None:
                raise ProspectiveConflictError(
                    f"observed target has no complete frozen window: {prediction.session_date}/{event_id}"
                )
            label = int(target["label"])
            label_status = str(target["label_status"])
            if label != window.label or label_status != window.label_status:
                raise ProspectiveConflictError(
                    f"target label conflicts with frozen predicate: {prediction.session_date}/{event_id}"
                )
            first_event_session = (
                window.first_event_session.date().isoformat()
                if window.first_event_session is not None
                else None
            )
            expected = {
                "schema_version": PROSPECTIVE_SCHEMA_VERSION,
                "record_type": "OUTCOME_RESOLVED",
                "scientific_cohort_id": SCIENTIFIC_COHORT_ID,
                "activation_tag": ACTIVATION_TAG,
                "session_date": prediction.session_date,
                "event_id": event_id,
                "horizon_sessions": horizon,
                "valid_through_session": valid_through,
                "outcome_available_at": available_at,
                "resolved_at": now.isoformat(),
                "resolved_late": now > outcome_at,
                "label": label,
                "label_status": label_status,
                "first_event_session": first_event_session,
                "prediction": prediction.binding.as_dict(),
                "target_ledger": target_binding.as_dict(),
                "resolver_release_id": resolver_release_id,
            }
            path = outcome_record_path(root, prediction.session_date, event_id)
            if path.exists():
                existing, _ = read_outcome_record(root, prediction.session_date, event_id)
                _assert_existing_outcome(existing, expected)
                existing_outcomes += 1
                continue
            write_outcome_record(root, expected)
            created_outcomes += 1

    return OutcomeResolutionSummary(
        status="CURRENT",
        checked_predictions=len(predictions),
        eligible_events=eligible_events,
        due_events=due_events,
        pending_events=pending_events,
        created_outcomes=created_outcomes,
        existing_outcomes=existing_outcomes,
    )
