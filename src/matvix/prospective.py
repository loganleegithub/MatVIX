from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import jsonschema

from matvix.calendar import add_sessions, decision_as_of
from matvix.constants import BASE_RATE_ONLY_EVENTS, EVENT_HORIZONS, EVENT_ORDER

PROSPECTIVE_SCHEMA_VERSION = "1.0.0"
SCIENTIFIC_COHORT_ID = "MATVIX_V3_0_1_CORE"
ACTIVATION_TAG = "matvix-prospective-001-activation"

PREDICTION_SCHEMA_NAME = "prospective_prediction.schema.json"
OUTCOME_SCHEMA_NAME = "prospective_outcome.schema.json"


class ProspectiveEvidenceError(RuntimeError):
    """Base error for the local prospective evidence store."""


class ProspectiveValidationError(ProspectiveEvidenceError):
    """A prospective record does not satisfy its frozen schema or semantics."""


class ProspectiveConflictError(ProspectiveEvidenceError):
    """A logical evidence path already contains different bytes."""


class ProspectiveCorruptionError(ProspectiveEvidenceError):
    """An existing evidence file is unreadable, mutable, or otherwise invalid."""


@dataclass(frozen=True)
class EvidenceBinding:
    relative_path: str
    sha256: str
    bytes: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "bytes": self.bytes,
        }


@dataclass(frozen=True)
class ImmutableWriteResult:
    path: Path
    binding: EvidenceBinding
    created: bool


@dataclass(frozen=True)
class ActivationIdentity:
    activated: bool
    capture_ready: bool
    activation_commit: str | None
    head_commit: str | None
    reason: str

    @property
    def runtime_release_id(self) -> str | None:
        return f"git:{self.head_commit}" if self.head_commit is not None else None


def prediction_record_path(project_dir: str | Path, session_date: str) -> Path:
    session = _normalized_date(session_date, field="session_date")
    return (
        Path(project_dir).resolve()
        / "data"
        / "prospective"
        / "core"
        / "predictions"
        / f"{session}.json"
    )


def outcome_record_path(project_dir: str | Path, session_date: str, event_id: str) -> Path:
    session = _normalized_date(session_date, field="session_date")
    if event_id not in EVENT_HORIZONS:
        raise ProspectiveValidationError(f"unknown event_id: {event_id}")
    return (
        Path(project_dir).resolve()
        / "data"
        / "prospective"
        / "core"
        / "outcomes"
        / session
        / f"{event_id}.json"
    )


def _normalized_date(value: object, *, field: str) -> str:
    try:
        parsed = datetime.strptime(str(value), "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise ProspectiveValidationError(f"{field} must be an ISO calendar date") from exc
    normalized = parsed.date().isoformat()
    if normalized != value:
        raise ProspectiveValidationError(f"{field} must be normalized as YYYY-MM-DD")
    return normalized


def _schema_path(name: str) -> Path:
    return Path(__file__).resolve().parents[2] / "schemas" / name


def _load_schema(name: str) -> dict[str, Any]:
    try:
        loaded = json.loads(_schema_path(name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveValidationError(f"prospective schema is unavailable: {name}") from exc
    if not isinstance(loaded, dict):
        raise ProspectiveValidationError(f"prospective schema is not an object: {name}")
    return cast(dict[str, Any], loaded)


def _validate_schema(payload: Mapping[str, Any], schema_name: str) -> None:
    validator = jsonschema.Draft202012Validator(
        _load_schema(schema_name), format_checker=jsonschema.FormatChecker()
    )
    errors = sorted(validator.iter_errors(dict(payload)), key=lambda error: list(error.path))
    if errors:
        details = "; ".join(
            f"{'/'.join(map(str, error.path)) or '<root>'}: {error.message}"
            for error in errors
        )
        raise ProspectiveValidationError(f"prospective schema validation failed: {details}")


def validate_prediction_record(payload: Mapping[str, Any]) -> None:
    _validate_schema(payload, PREDICTION_SCHEMA_NAME)
    session = _normalized_date(payload["session_date"], field="session_date")
    decision_time = datetime.fromisoformat(str(payload["decision_as_of"]))
    captured_time = datetime.fromisoformat(str(payload["captured_at"]))
    if decision_time.tzinfo is None or captured_time.tzinfo is None:
        raise ProspectiveValidationError("prediction timestamps must be timezone-aware")
    if captured_time < decision_time:
        raise ProspectiveValidationError("prediction cannot be captured before decision_as_of")
    snapshot = cast(Mapping[str, Any], payload["snapshot"])
    expected_snapshot_path = f"outputs/daily/{session}.json"
    if snapshot["relative_path"] != expected_snapshot_path:
        raise ProspectiveValidationError(
            f"snapshot path must be {expected_snapshot_path}: {snapshot['relative_path']}"
        )
    events = cast(Mapping[str, Mapping[str, Any]], payload["events"])
    for event_id in EVENT_ORDER:
        event = events[event_id]
        if event["event_id"] != event_id:
            raise ProspectiveValidationError(f"event key/id mismatch: {event_id}")
        if event["horizon_sessions"] != EVENT_HORIZONS[event_id]:
            raise ProspectiveValidationError(f"event horizon mismatch: {event_id}")
        eligible = event["event_status"] == "ELIGIBLE"
        if eligible != (event["valid_through_session"] is not None):
            raise ProspectiveValidationError(f"valid-through eligibility mismatch: {event_id}")
        if eligible != (event["outcome_available_at"] is not None):
            raise ProspectiveValidationError(f"outcome schedule eligibility mismatch: {event_id}")
        if eligible:
            expected_valid_through = add_sessions(session, EVENT_HORIZONS[event_id]).date().isoformat()
            if event["valid_through_session"] != expected_valid_through:
                raise ProspectiveValidationError(f"valid-through horizon mismatch: {event_id}")
            expected_outcome_at = decision_as_of(expected_valid_through).isoformat()
            if event["outcome_available_at"] != expected_outcome_at:
                raise ProspectiveValidationError(f"outcome schedule mismatch: {event_id}")
        if event_id in BASE_RATE_ONLY_EVENTS and event["candidate_probability"] is not None:
            raise ProspectiveValidationError(f"BASE_RATE_ONLY candidate must be null: {event_id}")
        if event["model_status"] == "BASE_RATE_ONLY":
            if event["published_probability"] != event["causal_base_rate"]:
                raise ProspectiveValidationError(
                    f"BASE_RATE_ONLY publication must equal causal BaseRate: {event_id}"
                )


def validate_outcome_record(payload: Mapping[str, Any]) -> None:
    _validate_schema(payload, OUTCOME_SCHEMA_NAME)
    session = _normalized_date(payload["session_date"], field="session_date")
    event_id = str(payload["event_id"])
    if payload["horizon_sessions"] != EVENT_HORIZONS[event_id]:
        raise ProspectiveValidationError(f"event horizon mismatch: {event_id}")
    prediction = cast(Mapping[str, Any], payload["prediction"])
    expected_prediction_path = f"data/prospective/core/predictions/{session}.json"
    if prediction["relative_path"] != expected_prediction_path:
        raise ProspectiveValidationError(
            f"prediction path must be {expected_prediction_path}: {prediction['relative_path']}"
        )
    target_ledger = cast(Mapping[str, Any], payload["target_ledger"])
    if target_ledger["relative_path"] != "data/probability/target_ledger.parquet":
        raise ProspectiveValidationError("outcome must bind the canonical target ledger")
    expected_valid_through = add_sessions(session, EVENT_HORIZONS[event_id]).date().isoformat()
    if payload["valid_through_session"] != expected_valid_through:
        raise ProspectiveValidationError(f"valid-through horizon mismatch: {event_id}")
    expected_outcome_at = decision_as_of(expected_valid_through).isoformat()
    if payload["outcome_available_at"] != expected_outcome_at:
        raise ProspectiveValidationError(f"outcome schedule mismatch: {event_id}")
    label = int(payload["label"])
    expected_status = f"OBSERVED_{label}"
    if payload["label_status"] != expected_status:
        raise ProspectiveValidationError(f"label/status mismatch: {event_id}")
    first_event_session = payload["first_event_session"]
    if (label == 0) != (first_event_session is None):
        raise ProspectiveValidationError(f"first-event/label mismatch: {event_id}")
    if first_event_session is not None:
        first = _normalized_date(first_event_session, field="first_event_session")
        if not session < first <= payload["valid_through_session"]:
            raise ProspectiveValidationError(f"first event falls outside frozen horizon: {event_id}")
    outcome_at = datetime.fromisoformat(str(payload["outcome_available_at"]))
    resolved_at = datetime.fromisoformat(str(payload["resolved_at"]))
    if outcome_at.tzinfo is None or resolved_at.tzinfo is None:
        raise ProspectiveValidationError("outcome and resolution timestamps must be timezone-aware")
    if resolved_at < outcome_at:
        raise ProspectiveValidationError(f"outcome resolved before it became available: {event_id}")
    if bool(payload["resolved_late"]) != (resolved_at > outcome_at):
        raise ProspectiveValidationError(f"resolved_late mismatch: {event_id}")


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    try:
        encoded = json.dumps(
            dict(payload),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ProspectiveValidationError("prospective record is not canonical JSON") from exc
    return (encoded + "\n").encode("utf-8")


def _sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _relative_path(project_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(project_dir.resolve()).as_posix()
    except ValueError as exc:
        raise ProspectiveValidationError(f"evidence path escapes project root: {path}") from exc


def _stable_content(path: Path) -> tuple[bytes, os.stat_result]:
    for _ in range(2):
        try:
            before = path.lstat()
            if not stat.S_ISREG(before.st_mode):
                raise ProspectiveCorruptionError(f"evidence path is not a regular file: {path}")
            content = path.read_bytes()
            after = path.lstat()
        except ProspectiveCorruptionError:
            raise
        except OSError as exc:
            raise ProspectiveCorruptionError(f"evidence file is unreadable: {path}") from exc
        before_token = (before.st_ino, before.st_mtime_ns, before.st_size, before.st_mode)
        after_token = (after.st_ino, after.st_mtime_ns, after.st_size, after.st_mode)
        if before_token == after_token and len(content) == after.st_size:
            return content, after
    raise ProspectiveCorruptionError(f"evidence file changed while being read: {path}")


def _read_json_object(content: bytes, *, path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProspectiveCorruptionError(f"evidence file is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ProspectiveCorruptionError(f"evidence JSON is not an object: {path}")
    return cast(dict[str, Any], payload)


def binding_for_file(project_dir: str | Path, path: str | Path) -> EvidenceBinding:
    root = Path(project_dir).resolve()
    target = Path(path).resolve()
    content, _ = _stable_content(target)
    return EvidenceBinding(
        relative_path=_relative_path(root, target),
        sha256=_sha256(content),
        bytes=len(content),
    )


def read_prediction_record(
    project_dir: str | Path, session_date: str
) -> tuple[dict[str, Any], EvidenceBinding]:
    root = Path(project_dir).resolve()
    path = prediction_record_path(root, session_date)
    content, metadata = _stable_content(path)
    if stat.S_IMODE(metadata.st_mode) != 0o444:
        raise ProspectiveCorruptionError(f"prospective evidence is not read-only: {path}")
    payload = _read_json_object(content, path=path)
    validate_prediction_record(payload)
    binding = EvidenceBinding(
        relative_path=_relative_path(root, path),
        sha256=_sha256(content),
        bytes=len(content),
    )
    return payload, binding


def read_outcome_record(
    project_dir: str | Path, session_date: str, event_id: str
) -> tuple[dict[str, Any], EvidenceBinding]:
    root = Path(project_dir).resolve()
    path = outcome_record_path(root, session_date, event_id)
    content, metadata = _stable_content(path)
    if stat.S_IMODE(metadata.st_mode) != 0o444:
        raise ProspectiveCorruptionError(f"prospective evidence is not read-only: {path}")
    payload = _read_json_object(content, path=path)
    validate_outcome_record(payload)
    binding = EvidenceBinding(
        relative_path=_relative_path(root, path),
        sha256=_sha256(content),
        bytes=len(content),
    )
    return payload, binding


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def activation_identity(project_dir: str | Path) -> ActivationIdentity:
    """Resolve the annotated activation tag and the exact running Git release."""

    root = Path(project_dir).resolve()
    head_result = _run_git(root, "rev-parse", "--verify", "HEAD")
    head = head_result.stdout.strip() if head_result.returncode == 0 else None
    if head is not None and (len(head) != 40 or any(char not in "0123456789abcdef" for char in head)):
        head = None

    ref = f"refs/tags/{ACTIVATION_TAG}"
    type_result = _run_git(root, "cat-file", "-t", ref)
    if type_result.returncode != 0:
        return ActivationIdentity(False, False, None, head, "ACTIVATION_TAG_ABSENT")
    if type_result.stdout.strip() != "tag":
        return ActivationIdentity(True, False, None, head, "ACTIVATION_TAG_NOT_ANNOTATED")
    tag_result = _run_git(root, "rev-parse", "--verify", f"{ref}^{{commit}}")
    activation_commit = tag_result.stdout.strip() if tag_result.returncode == 0 else None
    if activation_commit is None or len(activation_commit) != 40:
        return ActivationIdentity(True, False, None, head, "ACTIVATION_TAG_UNPEELABLE")
    if head is None:
        return ActivationIdentity(True, False, activation_commit, None, "HEAD_UNAVAILABLE")
    ancestor = _run_git(root, "merge-base", "--is-ancestor", activation_commit, head)
    if ancestor.returncode != 0:
        return ActivationIdentity(
            True,
            False,
            activation_commit,
            head,
            "RUNTIME_NOT_DESCENDED_FROM_ACTIVATION",
        )
    dirty = _run_git(root, "status", "--porcelain", "--untracked-files=no")
    if dirty.returncode != 0:
        return ActivationIdentity(True, False, activation_commit, head, "WORKTREE_STATUS_FAILED")
    if dirty.stdout.strip():
        return ActivationIdentity(True, False, activation_commit, head, "TRACKED_WORKTREE_DIRTY")
    return ActivationIdentity(True, True, activation_commit, head, "ACTIVE_CLEAN_RELEASE")


def capture_prediction_record(
    *,
    project_dir: str | Path,
    snapshot: Mapping[str, Any],
    probability_metadata: Mapping[str, Any],
    snapshot_path: str | Path,
    captured_at: datetime,
    runtime_release_id: str,
) -> ImmutableWriteResult:
    """Create or idempotently recover one exact prediction before its receipt."""

    root = Path(project_dir).resolve()
    session = _normalized_date(snapshot.get("session_date"), field="session_date")
    evidence_path = prediction_record_path(root, session)
    stable_captured_at = captured_at
    if evidence_path.exists():
        existing, _ = read_prediction_record(root, session)
        try:
            stable_captured_at = datetime.fromisoformat(str(existing["captured_at"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ProspectiveCorruptionError(
                f"existing prediction captured_at is invalid: {evidence_path}"
            ) from exc
    record = build_prediction_record(
        snapshot=snapshot,
        probability_metadata=probability_metadata,
        snapshot_binding=binding_for_file(root, snapshot_path).as_dict(),
        captured_at=stable_captured_at,
        runtime_release_id=runtime_release_id,
    )
    return write_prediction_record(root, record)


def validate_receipt_evidence(
    project_dir: str | Path,
    session_date: str,
    payload: Mapping[str, Any],
    *,
    snapshot_binding: Mapping[str, Any],
) -> None:
    """Validate the receipt's prospective state and any bound prediction bytes."""

    expected_keys = {
        "schema_version",
        "status",
        "scientific_cohort_id",
        "activation_tag",
        "activation_commit",
        "runtime_release_id",
        "captured_at",
        "prediction",
        "capture_error",
    }
    if set(payload) != expected_keys:
        raise ProspectiveValidationError("receipt prospective evidence fields do not match contract")
    if payload["schema_version"] != PROSPECTIVE_SCHEMA_VERSION:
        raise ProspectiveValidationError("receipt prospective schema version mismatch")
    if payload["scientific_cohort_id"] != SCIENTIFIC_COHORT_ID:
        raise ProspectiveValidationError("receipt scientific cohort mismatch")
    if payload["activation_tag"] != ACTIVATION_TAG:
        raise ProspectiveValidationError("receipt activation tag mismatch")
    try:
        captured_at = datetime.fromisoformat(str(payload["captured_at"]))
    except (TypeError, ValueError) as exc:
        raise ProspectiveValidationError("receipt capture timestamp is invalid") from exc
    if captured_at.tzinfo is None:
        raise ProspectiveValidationError("receipt capture timestamp must be timezone-aware")
    status_value = payload["status"]
    if status_value not in {"LOCAL_CAPTURED", "EVIDENCE_CAPTURE_GAP", "PRE_ACTIVATION"}:
        raise ProspectiveValidationError("receipt prospective status is invalid")
    if status_value != "LOCAL_CAPTURED":
        if payload["prediction"] is not None:
            raise ProspectiveValidationError("non-captured receipt cannot bind a prediction")
        if status_value == "PRE_ACTIVATION" and payload["capture_error"] is not None:
            raise ProspectiveValidationError("pre-activation receipt cannot have a capture error")
        if status_value == "EVIDENCE_CAPTURE_GAP" and not isinstance(
            payload["capture_error"], str
        ):
            raise ProspectiveValidationError("capture gap must identify an error")
        return
    if payload["capture_error"] is not None:
        raise ProspectiveValidationError("captured receipt cannot have a capture error")
    if not isinstance(payload["activation_commit"], str) or not isinstance(
        payload["runtime_release_id"], str
    ):
        raise ProspectiveValidationError("captured receipt Git identity is missing")
    prediction_binding = payload["prediction"]
    if not isinstance(prediction_binding, Mapping):
        raise ProspectiveValidationError("captured receipt prediction binding is missing")
    record, actual_binding = read_prediction_record(project_dir, session_date)
    if dict(prediction_binding) != actual_binding.as_dict():
        raise ProspectiveValidationError("receipt prediction binding does not match local bytes")
    if record["runtime_release_id"] != payload["runtime_release_id"]:
        raise ProspectiveValidationError("receipt/prediction runtime release mismatch")
    if record["captured_at"] != payload["captured_at"]:
        raise ProspectiveValidationError("receipt/prediction capture timestamp mismatch")
    snapshot = cast(Mapping[str, Any], record["snapshot"])
    expected_snapshot = {
        "relative_path": f"outputs/daily/{session_date}.json",
        "sha256": snapshot_binding.get("snapshot_sha256"),
        "bytes": snapshot_binding.get("snapshot_size"),
    }
    if dict(snapshot) != expected_snapshot:
        raise ProspectiveValidationError("prediction does not bind the accepted snapshot")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_immutable(
    project_dir: Path,
    path: Path,
    payload: Mapping[str, Any],
) -> ImmutableWriteResult:
    encoded = _canonical_json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        existing, metadata = _stable_content(path)
        if existing != encoded:
            raise ProspectiveConflictError(
                f"prospective evidence conflict; existing bytes preserved: {path}"
            ) from None
        if stat.S_IMODE(metadata.st_mode) != 0o444:
            raise ProspectiveCorruptionError(
                f"prospective evidence is not read-only: {path}"
            ) from None
    else:
        created = True
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(path, 0o444)
            _fsync_directory(path.parent)
        except Exception:
            # A partial exclusive file is deliberate evidence of a failed
            # capture. Never overwrite or silently remove it on a later run.
            raise
    content, metadata = _stable_content(path)
    if content != encoded:
        raise ProspectiveCorruptionError(f"prospective evidence bytes changed after write: {path}")
    if stat.S_IMODE(metadata.st_mode) != 0o444:
        raise ProspectiveCorruptionError(f"prospective evidence is not read-only: {path}")
    return ImmutableWriteResult(
        path=path,
        binding=EvidenceBinding(
            relative_path=_relative_path(project_dir, path),
            sha256=_sha256(content),
            bytes=len(content),
        ),
        created=created,
    )


def write_prediction_record(
    project_dir: str | Path, payload: Mapping[str, Any]
) -> ImmutableWriteResult:
    validate_prediction_record(payload)
    root = Path(project_dir).resolve()
    target = prediction_record_path(root, str(payload["session_date"]))
    return _write_immutable(root, target, payload)


def write_outcome_record(
    project_dir: str | Path, payload: Mapping[str, Any]
) -> ImmutableWriteResult:
    validate_outcome_record(payload)
    root = Path(project_dir).resolve()
    target = outcome_record_path(root, str(payload["session_date"]), str(payload["event_id"]))
    return _write_immutable(root, target, payload)


def build_prediction_record(
    *,
    snapshot: Mapping[str, Any],
    probability_metadata: Mapping[str, Any],
    snapshot_binding: Mapping[str, Any],
    captured_at: datetime,
    runtime_release_id: str,
) -> dict[str, Any]:
    if captured_at.tzinfo is None:
        raise ProspectiveValidationError("captured_at must be timezone-aware")
    session = _normalized_date(snapshot.get("session_date"), field="session_date")
    events_payload = snapshot.get("probability_judgment")
    if not isinstance(events_payload, Mapping):
        raise ProspectiveValidationError("snapshot probability_judgment is missing")
    events: dict[str, dict[str, Any]] = {}
    for event_id in EVENT_ORDER:
        event = events_payload.get(event_id)
        if not isinstance(event, Mapping):
            raise ProspectiveValidationError(f"snapshot event is missing: {event_id}")
        metadata = probability_metadata.get(event_id)
        event_metadata = metadata if isinstance(metadata, Mapping) else {}
        candidate = (
            event_metadata.get("candidate_probability")
            if event_metadata.get("publication_method") == "ROLLING_INTERCEPT_252"
            else None
        )
        if event_id in BASE_RATE_ONLY_EVENTS:
            candidate = None
        valid_through = event.get("valid_through_session")
        outcome_available_at = (
            decision_as_of(valid_through).isoformat() if valid_through is not None else None
        )
        events[event_id] = {
            "event_id": event_id,
            "event_status": event.get("event_status"),
            "model_status": event.get("model_status"),
            "probability_kind": event.get("probability_kind"),
            "horizon_sessions": EVENT_HORIZONS[event_id],
            "published_probability": event.get("probability"),
            "candidate_probability": candidate,
            "causal_base_rate": event.get("base_rate"),
            "valid_through_session": valid_through,
            "outcome_available_at": outcome_available_at,
        }
    record = {
        "schema_version": PROSPECTIVE_SCHEMA_VERSION,
        "record_type": "PREDICTION_PUBLISHED",
        "scientific_cohort_id": SCIENTIFIC_COHORT_ID,
        "activation_tag": ACTIVATION_TAG,
        "session_date": session,
        "decision_as_of": snapshot.get("decision_as_of"),
        "captured_at": captured_at.isoformat(),
        "runtime_release_id": runtime_release_id,
        "snapshot": dict(snapshot_binding),
        "events": events,
    }
    validate_prediction_record(record)
    return record
