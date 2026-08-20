from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest
import yaml
from conftest import make_observations, make_vx_history

from matvix.daily_update import load_source_manifest
from matvix.pipeline import build_state_history
from matvix.source_identity import OFFICIAL_SOURCE_IDENTITIES

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_frozen_source_identities_match_the_checked_in_manifest() -> None:
    loaded = yaml.safe_load((PROJECT_ROOT / "configs/source_manifest.yaml").read_text("utf-8"))
    configured = loaded["series"]

    assert set(configured) == set(OFFICIAL_SOURCE_IDENTITIES)
    for series_id, identity in OFFICIAL_SOURCE_IDENTITIES.items():
        assert configured[series_id] == {
            "source": identity.source,
            "source_symbol": identity.source_symbol,
            "vintage_kind": identity.vintage_kind,
        }


def test_manifest_loader_rejects_source_identity_policy_drift(tmp_path: Path) -> None:
    shutil.copytree(PROJECT_ROOT / "configs", tmp_path / "configs")
    path = tmp_path / "configs/source_manifest.yaml"
    loaded = yaml.safe_load(path.read_text("utf-8"))
    loaded["series"]["SPX_CLOSE"]["source_symbol"] = "SP500"
    path.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="source manifest identity policy mismatch"):
        load_source_manifest(tmp_path)


@pytest.mark.parametrize(
    ("column", "wrong_value"),
    [
        ("source", "FRED"),
        ("source_symbol", "SP500"),
        ("vintage_kind", "OBSERVED_PIT"),
    ],
)
def test_formal_state_history_rejects_wrong_observation_identity(
    column: str, wrong_value: str
) -> None:
    observations = make_observations("2024-01-02", "2025-06-30")
    sessions = pd.DatetimeIndex(sorted(pd.to_datetime(observations["session_date"]).unique()))
    vx = make_vx_history(sessions)
    rejected_session = sessions[80]
    mask = pd.to_datetime(observations["session_date"]).eq(rejected_session) & observations[
        "series_id"
    ].eq("SPX_CLOSE")
    observations.loc[mask, column] = wrong_value

    features, states = build_state_history(
        observations, vx, reference_sessions=40, minimum_valid=20
    )
    feature = features.loc[features["session_date"].eq(rejected_session)].iloc[-1]
    state = states.loc[states["session_date"].eq(rejected_session)].iloc[-1]

    assert pd.isna(feature["spx_close"])
    assert state["data_status"] != "OK"


@pytest.mark.parametrize(
    ("column", "wrong_value"),
    [
        ("source", "CBOE"),
        ("source_symbol", "VX_WEEKLY"),
        ("vintage_kind", "OBSERVED_PIT"),
    ],
)
def test_formal_state_history_rejects_wrong_vx_identity(column: str, wrong_value: str) -> None:
    observations = make_observations("2024-01-02", "2025-06-30")
    sessions = pd.DatetimeIndex(sorted(pd.to_datetime(observations["session_date"]).unique()))
    vx = make_vx_history(sessions)
    rejected_session = sessions[80]
    mask = pd.to_datetime(vx["session_date"]).eq(rejected_session) & vx["contract_id"].eq(
        "VX_TEST_1"
    )
    vx.loc[mask, column] = wrong_value

    _, states = build_state_history(observations, vx, reference_sessions=40, minimum_valid=20)
    state = states.loc[states["session_date"].eq(rejected_session)].iloc[-1]

    assert state["data_status"] != "OK"


def test_wrong_later_revision_cannot_displace_an_official_observation() -> None:
    observations = make_observations("2024-01-02", "2025-06-30")
    sessions = pd.DatetimeIndex(sorted(pd.to_datetime(observations["session_date"]).unique()))
    vx = make_vx_history(sessions)
    target = sessions[80]
    official = observations.loc[
        pd.to_datetime(observations["session_date"]).eq(target)
        & observations["series_id"].eq("SPX_CLOSE")
    ].iloc[-1]
    wrong_later = official.copy()
    wrong_later["value"] = 999_999.0
    wrong_later["source"] = "FRED"
    wrong_later["source_symbol"] = "SP500"
    wrong_later["ingested_at"] = "2026-02-01T00:00:00+00:00"
    wrong_later["revision_id"] = "wrong-later-revision"
    observations = pd.concat([observations, wrong_later.to_frame().T], ignore_index=True)

    features, _ = build_state_history(observations, vx, reference_sessions=40, minimum_valid=20)
    selected = features.loc[features["session_date"].eq(target)].iloc[-1]

    assert selected["spx_close"] == pytest.approx(float(official["value"]))
