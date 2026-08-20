from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from typer.testing import CliRunner

import matvix.cli as cli
from matvix.config_contract import ConfigContractReport
from matvix.daily_update import project_publication_lock, with_snapshot_publication_binding
from matvix.http_runtime import find_latest_accepted_snapshot
from matvix.pipeline import ProjectPaths
from matvix.storage import read_json, write_json


def _stub_acceptance_chain(
    monkeypatch: Any,
    *,
    snapshot: dict[str, Any],
) -> None:
    session = str(snapshot["session_date"])
    states = pd.DataFrame([{"session_date": session, "data_status": "OK"}])
    monkeypatch.setattr(
        cli,
        "load_persisted_inputs",
        lambda _paths: (pd.DataFrame(), pd.DataFrame()),
    )
    monkeypatch.setattr(cli, "load_persisted_states", lambda _paths: states)
    monkeypatch.setattr(
        cli,
        "resolve_persisted_probability_artifacts",
        lambda *_args, **_kwargs: (
            pd.DataFrame(),
            pd.DataFrame(),
            {"state_history": {"relevant_columns_digest": "sha256:test"}},
            "EXACT_CACHE_HIT",
        ),
    )
    monkeypatch.setattr(
        cli,
        "build_snapshot_payload",
        lambda *_args, **_kwargs: (snapshot, {}, pd.DataFrame(), pd.DataFrame()),
    )
    monkeypatch.setattr(
        cli,
        "build_real_acceptance_report",
        lambda **_kwargs: {"session_date": session, "passed": True, "gates": []},
    )
    monkeypatch.setattr(
        cli,
        "validate_frozen_config",
        lambda _root: ConfigContractReport(
            versions={"source_manifest.yaml": "1.0.0"},
            config_bundle_digest="sha256:config",
        ),
    )


def test_accept_real_signs_exact_daily_snapshot_for_http_publication(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    session = "2026-08-18"
    snapshot = {"session_date": session, "data_status": "OK", "market_story": {}}
    paths = ProjectPaths(tmp_path)
    write_json(snapshot, paths.daily_output_dir / f"{session}.json")
    _stub_acceptance_chain(monkeypatch, snapshot=snapshot)

    result = CliRunner().invoke(
        cli.app,
        ["accept-real", "--date", session, "--project-dir", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    accepted = find_latest_accepted_snapshot(tmp_path)
    assert accepted is not None
    assert accepted.session_date == session


def test_accept_real_refuses_to_sign_a_different_persisted_generation(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    session = "2026-08-18"
    recomputed = {"session_date": session, "data_status": "OK", "market_story": {}}
    paths = ProjectPaths(tmp_path)
    write_json(
        {**recomputed, "market_story": {"phase": "STALE"}},
        paths.daily_output_dir / f"{session}.json",
    )
    _stub_acceptance_chain(monkeypatch, snapshot=recomputed)

    result = CliRunner().invoke(
        cli.app,
        ["accept-real", "--date", session, "--project-dir", str(tmp_path)],
    )

    assert result.exit_code == 2
    assert "does not match the persisted" in result.output
    assert not (paths.root / "artifacts/acceptance" / f"real_acceptance_{session}.json").exists()


def test_accept_real_never_races_an_active_daily_publisher(tmp_path: Path) -> None:
    session = "2026-08-18"

    with project_publication_lock(tmp_path, session, current=datetime.now(UTC)):
        result = CliRunner().invoke(
            cli.app,
            ["accept-real", "--date", session, "--project-dir", str(tmp_path)],
        )

    assert result.exit_code == 6
    assert "another MatVIX publisher owns the project lock" in result.output


def test_formal_acceptance_is_rejected_before_decision_time(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    session = "2026-08-18"
    snapshot = {"session_date": session, "data_status": "OK", "market_story": {}}
    paths = ProjectPaths(tmp_path)
    write_json(snapshot, paths.daily_output_dir / f"{session}.json")
    _stub_acceptance_chain(monkeypatch, snapshot=snapshot)
    due = cli.decision_as_of(pd.Timestamp(session))
    monkeypatch.setattr(cli, "_current_time", lambda: due - timedelta(microseconds=1))

    result = CliRunner().invoke(
        cli.app,
        ["accept-real", "--date", session, "--project-dir", str(tmp_path)],
    )

    assert result.exit_code == 2
    assert "Formal acceptance is gated until" in result.output
    assert find_latest_accepted_snapshot(tmp_path) is None


def test_formal_acceptance_is_allowed_exactly_at_decision_time(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    session = "2026-08-18"
    snapshot = {"session_date": session, "data_status": "OK", "market_story": {}}
    paths = ProjectPaths(tmp_path)
    write_json(snapshot, paths.daily_output_dir / f"{session}.json")
    _stub_acceptance_chain(monkeypatch, snapshot=snapshot)
    monkeypatch.setattr(
        cli,
        "_current_time",
        lambda: cli.decision_as_of(pd.Timestamp(session)),
    )

    result = CliRunner().invoke(
        cli.app,
        ["accept-real", "--date", session, "--project-dir", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    assert find_latest_accepted_snapshot(tmp_path) is not None


def test_failed_reaccept_never_overwrites_existing_passing_receipt(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    session = "2026-08-18"
    snapshot = {"session_date": session, "data_status": "OK", "market_story": {}}
    paths = ProjectPaths(tmp_path)
    snapshot_path = paths.daily_output_dir / f"{session}.json"
    write_json(snapshot, snapshot_path)
    formal_receipt = (
        paths.root / "artifacts" / "acceptance" / f"real_acceptance_{session}.json"
    )
    passing = with_snapshot_publication_binding(
        {"session_date": session, "passed": True, "gates": []},
        snapshot_path,
    )
    write_json(passing, formal_receipt)
    original_receipt = formal_receipt.read_bytes()
    _stub_acceptance_chain(monkeypatch, snapshot=snapshot)
    monkeypatch.setattr(
        cli,
        "build_real_acceptance_report",
        lambda **_kwargs: {
            "session_date": session,
            "passed": False,
            "gates": [{"name": "real_gate", "passed": False}],
        },
    )
    monkeypatch.setattr(
        cli,
        "_current_time",
        lambda: cli.decision_as_of(pd.Timestamp(session)),
    )

    result = CliRunner().invoke(
        cli.app,
        ["accept-real", "--date", session, "--project-dir", str(tmp_path)],
    )

    assert result.exit_code == 4
    assert formal_receipt.read_bytes() == original_receipt
    accepted = find_latest_accepted_snapshot(tmp_path)
    assert accepted is not None and accepted.session_date == session
    failed_attempt = (
        formal_receipt.parent
        / "attempts"
        / f"real_acceptance_{session}_latest_failed.json"
    )
    assert read_json(failed_attempt)["passed"] is False
