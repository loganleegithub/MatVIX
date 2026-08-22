from __future__ import annotations

import copy
import importlib.util
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from conftest import base_state_frame, make_observations, make_vx_history
from typer.testing import CliRunner

from matvix.cli import app
from matvix.dashboard import render_dashboard
from matvix.output import input_manifest_hash, validate_daily_output
from matvix.pipeline import (
    ProjectPaths,
    build_snapshot_payload,
    build_state_history,
    resolve_persisted_probability_artifacts,
)
from matvix.probability.walk_forward import ProbabilitySpec
from matvix.storage import ParquetDependencyError, read_json, read_parquet, write_parquet


@lru_cache(maxsize=1)
def _integration_history():
    observations = make_observations("2024-01-02", "2024-10-31")
    sessions = pd.DatetimeIndex(sorted(pd.to_datetime(observations["session_date"]).unique()))
    vx = make_vx_history(sessions)
    features, states = build_state_history(
        observations, vx, reference_sessions=40, minimum_valid=20
    )
    return observations, vx, features, states


def test_raw_to_state_history_and_snapshot_schema() -> None:
    observations, vx, features, states = _integration_history()
    ok = states.loc[states["data_status"] == "OK"]
    assert not ok.empty
    session = ok.iloc[-1]["session_date"]
    payload, metadata, targets, oof = build_snapshot_payload(
        states, observations, vx, session_date=session, formal_runtime_required=True
    )
    validate_daily_output(payload)
    assert payload["session_date"] == pd.Timestamp(session).date().isoformat()
    assert len(payload["market_story"]["scores"]) == 5
    assert set(payload["market_story"]["structure"]) == {
        "stress_tenor_scope",
        "mid_curve_pressure_state",
        "carry_environment_state",
    }
    assert len(payload["probability_judgment"]) == 4
    assert payload["observations"]["vx_contract_ids"]
    # On sandbox sklearn mismatch, formal probability correctly falls back or remains insufficient.
    assert all(
        event["model_status"] in {"BASE_RATE_ONLY", "INSUFFICIENT_HISTORY", "NOT_RUN"}
        for event in payload["probability_judgment"].values()
    )


def test_snapshot_accepts_arrow_array_curve_without_false_incomplete_issue() -> None:
    observations, vx, _, states = _integration_history()
    persisted_shape = states.copy()
    persisted_shape["vx_contract_ids"] = persisted_shape["vx_contract_ids"].map(
        lambda value: np.asarray(value, dtype=object)
    )
    session = persisted_shape.loc[persisted_shape["data_status"] == "OK", "session_date"].iloc[-1]

    payload = build_snapshot_payload(
        persisted_shape,
        observations,
        vx,
        session_date=session,
        formal_runtime_required=True,
    )[0]

    assert not any(issue.startswith("INCOMPLETE_VX_F1_F7") for issue in payload["issues"])


def test_replay_is_deterministic_for_same_history() -> None:
    observations, vx, _, states = _integration_history()
    session = states.loc[states["data_status"] == "OK", "session_date"].iloc[-1]
    first = build_snapshot_payload(
        states, observations, vx, session_date=session, formal_runtime_required=True
    )[0]
    second = build_snapshot_payload(
        states, observations, vx, session_date=session, formal_runtime_required=True
    )[0]
    assert json.dumps(first, sort_keys=True, ensure_ascii=False) == json.dumps(
        second, sort_keys=True, ensure_ascii=False
    )


def test_f4_f7_changes_are_session_based_and_replayable() -> None:
    _, _, features, _ = _integration_history()
    current = features.iloc[-1]
    previous5 = features.iloc[-6]
    previous10 = features.iloc[-11]

    assert current["d5_log_f4_f7_level"] == pytest.approx(
        np.log(current["f4_f7_level"] / previous5["f4_f7_level"])
    )
    assert current["d10_f4_f7_slope30"] == pytest.approx(
        current["f4_f7_slope30"] - previous10["f4_f7_slope30"]
    )
    assert current["d10_f4_f7_inversion_share"] == pytest.approx(
        current["f4_f7_inversion_share"] - previous10["f4_f7_inversion_share"]
    )


def test_future_raw_change_does_not_change_prior_snapshot() -> None:
    observations, vx, _, states = _integration_history()
    ok_dates = states.loc[states["data_status"] == "OK", "session_date"]
    session = ok_dates.iloc[-20]
    first = build_snapshot_payload(
        states, observations, vx, session_date=session, formal_runtime_required=True
    )[0]
    later_mask = pd.to_datetime(observations["session_date"]) > session
    changed = observations.copy()
    changed.loc[later_mask, "value"] = changed.loc[later_mask, "value"] * 10
    _, changed_states = build_state_history(changed, vx, reference_sessions=40, minimum_valid=20)
    second = build_snapshot_payload(
        changed_states, changed, vx, session_date=session, formal_runtime_required=True
    )[0]
    assert first == second


def test_manifest_hash_is_order_independent() -> None:
    frame = pd.DataFrame(
        [
            {"series_id": "B", "session_date": "2025-01-02", "revision_id": "2"},
            {"series_id": "A", "session_date": "2025-01-02", "revision_id": "1"},
        ]
    )
    assert input_manifest_hash(frame) == input_manifest_hash(frame.iloc[::-1])


def test_dashboard_score_probability_separation_and_order() -> None:
    observations, vx, _, states = _integration_history()
    session = states.loc[states["data_status"] == "OK", "session_date"].iloc[-1]
    payload = build_snapshot_payload(
        states, observations, vx, session_date=session, formal_runtime_required=True
    )[0]
    html = render_dashboard(payload, states)
    positions = [
        html.index("现在：五个状态答案与五个分数"),
        html.index("期限结构"),
        html.index("证据与改变条件"),
        html.index("接下来：四类状态转移概率"),
        html.index("1 / 5 / 20 日变化"),
        html.index("十五项原始指标与完整诊断"),
    ]
    assert positions == sorted(positions)
    assert "score-card" in html and "prob-card" in html
    assert "事件状态" in html and "概率类型" in html
    assert "历史状态路径" in html and "Baseline" in html
    assert "&quot;observations&quot;" in html


def test_dashboard_not_applicable_is_not_zero_percent() -> None:
    observations, vx, _, states = _integration_history()
    session = states.loc[states["data_status"] == "OK", "session_date"].iloc[-1]
    payload = build_snapshot_payload(
        states, observations, vx, session_date=session, formal_runtime_required=True
    )[0]
    first_event = next(iter(payload["probability_judgment"]))
    payload = copy.deepcopy(payload)
    payload["probability_judgment"][first_event] = {
        "event_status": "NOT_APPLICABLE",
        "model_status": "NOT_RUN",
        "probability_kind": None,
        "probability": None,
        "base_rate": None,
        "uplift": None,
        "valid_through_session": None,
        "interpretation": "当前状态已存在或该转移问题不适用",
    }
    html = render_dashboard(payload)
    assert "不适用 / 状态已存在" in html
    assert "0.0%" not in html


def test_cli_help_smoke() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in [
        "download-data",
        "import-data",
        "build-history",
        "build-snapshot",
        "train-probabilities",
        "accept-real",
        "daily-update",
        "runtime-status",
        "install-services",
        "replay",
        "test",
        "serve",
    ]:
        assert command in result.stdout


def test_parquet_round_trip_or_explicit_dependency_error(tmp_path: Path) -> None:
    frame = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    path = tmp_path / "test.parquet"
    if importlib.util.find_spec("pyarrow") is None:
        with pytest.raises(ParquetDependencyError):
            write_parquet(frame, path)
    else:
        write_parquet(frame, path)
        pd.testing.assert_frame_equal(read_parquet(path), frame)


def test_persisted_probability_cache_requires_and_reuses_contract(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    states = base_state_frame(30)
    spec = ProbabilitySpec(training_min=100)

    first = resolve_persisted_probability_artifacts(
        paths,
        states,
        spec=spec,
        formal_runtime_required=False,
    )
    assert first[3] == "FULL_REBUILD_MISSING_CACHE"
    assert paths.targets.exists()
    assert paths.oof.exists()
    assert paths.probability_artifact_contract.exists()
    contract = read_json(paths.probability_artifact_contract)
    assert contract["probability_spec"]["training_min"] == 100
    assert contract["runtime"]["scikit-learn"]
    assert contract["state_history"]["row_count"] == 30
    assert contract["state_history"]["relevant_columns_digest"].startswith("sha256:")

    second = resolve_persisted_probability_artifacts(
        paths,
        states,
        spec=spec,
        formal_runtime_required=False,
    )
    assert second[3] == "EXACT_CACHE_HIT"


def test_cli_reimport_unchanged_vendor_files_does_not_rewrite_parquet(
    tmp_path: Path,
) -> None:
    cboe_dir = tmp_path / "vendor" / "cboe"
    cfe_dir = tmp_path / "vendor" / "cfe"
    project_dir = tmp_path / "project"
    cboe_dir.mkdir(parents=True)
    cfe_dir.mkdir(parents=True)
    (cboe_dir / "VIX_History.csv").write_text(
        "DATE,OPEN,HIGH,LOW,CLOSE\n01/02/2025,17,19,16,18\n",
        encoding="utf-8",
    )
    (cfe_dir / "VX_2025-01-22.csv").write_text(
        "Trade Date,Futures,Settle\n2025-01-02,VX/F5,18.0\n",
        encoding="utf-8",
    )
    spx_csv = tmp_path / "SP500.csv"
    spx_csv.write_text(
        "observation_date,SP500\n2025-01-02,5900.00\n",
        encoding="utf-8",
    )
    arguments = [
        "import-data",
        "--cboe-dir",
        str(cboe_dir),
        "--cfe-dir",
        str(cfe_dir),
        "--spx-csv",
        str(spx_csv),
        "--spx-source",
        "FRED",
        "--project-dir",
        str(project_dir),
    ]
    runner = CliRunner()
    first = runner.invoke(app, arguments)
    assert first.exit_code == 0, first.output
    paths = ProjectPaths(project_dir)
    observations_before = paths.observations.read_bytes()
    vx_before = paths.vx_contracts.read_bytes()
    observation_mtime = paths.observations.stat().st_mtime_ns
    vx_mtime = paths.vx_contracts.stat().st_mtime_ns

    second = runner.invoke(app, arguments)

    assert second.exit_code == 0, second.output
    assert "observations=5 (unchanged)" in second.output
    assert "VX rows=1 (unchanged)" in second.output
    assert paths.observations.read_bytes() == observations_before
    assert paths.vx_contracts.read_bytes() == vx_before
    assert paths.observations.stat().st_mtime_ns == observation_mtime
    assert paths.vx_contracts.stat().st_mtime_ns == vx_mtime
