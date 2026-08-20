from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
from conftest import make_curve, make_observations, make_vx_history

from matvix.calendar import decision_as_of
from matvix.data.point_in_time import (
    filter_as_of,
    formal_vintage_eligible,
    merge_revision_history,
    select_historical_point_in_time,
    weakest_vintage,
)
from matvix.pipeline import build_state_history


def test_weakest_vintage_and_formal_eligibility() -> None:
    assert weakest_vintage(["OBSERVED_PIT", "ASSUMED_PIT"]) == "ASSUMED_PIT"
    assert weakest_vintage(["ASSUMED_PIT", "PROVIDER_BACKTESTED"]) == "PROVIDER_BACKTESTED"
    assert formal_vintage_eligible(["OBSERVED_PIT", "ASSUMED_PIT"])
    assert not formal_vintage_eligible(["OBSERVED_PIT", "PROVIDER_BACKTESTED"])


def test_filter_as_of_excludes_future_revision_and_backtested() -> None:
    session = pd.Timestamp("2025-01-02")
    base = {
        "series_id": "VIX_CLOSE",
        "session_date": session,
        "value": 20.0,
        "available_at": decision_as_of(session),
        "revision_id": "a",
        "vintage_kind": "ASSUMED_PIT",
    }
    rows = [
        base,
        {
            **base,
            "value": 21.0,
            "available_at": pd.Timestamp("2025-02-01", tz="UTC"),
            "revision_id": "b",
        },
        {**base, "value": 99.0, "revision_id": "c", "vintage_kind": "PROVIDER_BACKTESTED"},
    ]
    result = filter_as_of(pd.DataFrame(rows), decision_as_of(session))
    assert result.iloc[0]["value"] == 20.0


def test_historical_pit_selects_revision_available_on_that_day() -> None:
    session = pd.Timestamp("2025-01-02")
    cutoff = pd.Timestamp(decision_as_of(session)).tz_convert("UTC")
    frame = pd.DataFrame(
        [
            {
                "series_id": "X",
                "session_date": session,
                "available_at": cutoff - pd.Timedelta(minutes=1),
                "revision_id": "r1",
                "vintage_kind": "ASSUMED_PIT",
                "value": 1.0,
            },
            {
                "series_id": "X",
                "session_date": session,
                "available_at": cutoff + pd.Timedelta(days=2),
                "revision_id": "r2",
                "vintage_kind": "OBSERVED_PIT",
                "value": 2.0,
            },
        ]
    )
    result = select_historical_point_in_time(frame, entity_columns=["series_id"])
    assert result["revision_id"].tolist() == ["r1"]


def test_provider_backtested_cannot_enter_formal_percentile_or_future_state() -> None:
    observations = make_observations("2024-01-02", "2025-06-30")
    sessions = sorted(pd.to_datetime(observations["session_date"]).unique())
    vx = make_vx_history(pd.DatetimeIndex(sessions))
    bad_day = pd.Timestamp(sessions[50])
    mask = (pd.to_datetime(observations["session_date"]) == bad_day) & (
        observations["series_id"] == "VIX_CLOSE"
    )
    observations.loc[mask, "vintage_kind"] = "PROVIDER_BACKTESTED"
    observations.loc[mask, "value"] = 999.0
    features_bad, states_bad = build_state_history(
        observations, vx, reference_sessions=40, minimum_valid=20
    )

    clean = make_observations("2024-01-02", "2025-06-30")
    features_clean, states_clean = build_state_history(
        clean, vx, reference_sessions=40, minimum_valid=20
    )

    # The research-only value becomes a missing formal observation, never the 999 shock.
    bad_row = features_bad.loc[features_bad["session_date"] == bad_day].iloc[0]
    assert pd.isna(bad_row["vix_close"])
    assert states_bad.loc[states_bad["session_date"] == bad_day, "data_status"].iloc[0] != "OK"
    later = bad_day + pd.Timedelta(days=120)
    common_bad = features_bad.loc[
        features_bad["session_date"] >= later, ["session_date", "p_d5_log_vix"]
    ]
    common_clean = features_clean.loc[
        features_clean["session_date"] >= later, ["session_date", "p_d5_log_vix"]
    ]
    merged = common_bad.merge(common_clean, on="session_date", suffixes=("_bad", "_clean"))
    # Once the fixed 40-session reference window no longer includes the missing day, paths coincide.
    assert (
        merged["p_d5_log_vix_bad"].dropna() - merged["p_d5_log_vix_clean"].dropna()
    ).abs().max() < 1e-12


def test_provider_backtested_vx_row_is_excluded() -> None:
    curve = make_curve(vintage_kind="ASSUMED_PIT")
    curve.loc[0, "vintage_kind"] = "PROVIDER_BACKTESTED"
    selected = select_historical_point_in_time(curve, entity_columns=["contract_id"])
    assert "VX_TEST_1" not in selected["contract_id"].tolist()


def test_merge_revision_history_does_not_backdate_later_revision() -> None:
    session = pd.Timestamp("2025-01-02")
    original = {
        "series_id": "VIX_CLOSE",
        "session_date": session,
        "value": 20.0,
        "unit": "index_points",
        "source": "CBOE",
        "source_symbol": "VIX",
        "observed_at": "2025-01-02T16:15:00-05:00",
        "available_at": decision_as_of(session).isoformat(),
        "ingested_at": "2025-01-03T13:00:00+00:00",
        "revision_id": "sha256:original",
        "methodology_version": "CBOE_VIX_OFFICIAL_EOD",
        "vintage_kind": "ASSUMED_PIT",
    }
    revised = {
        **original,
        "value": 21.0,
        "ingested_at": "2025-02-01T15:30:00+00:00",
        "revision_id": "sha256:revised",
    }

    merged = merge_revision_history(
        pd.DataFrame([original]), pd.DataFrame([revised]), entity_columns=["series_id"]
    )

    assert len(merged) == 2
    revised_row = merged.loc[merged["revision_id"] == "sha256:revised"].iloc[0]
    assert pd.Timestamp(revised_row["available_at"]) == pd.Timestamp(revised["ingested_at"])
    historical = filter_as_of(merged, decision_as_of(session))
    current = filter_as_of(merged, datetime(2025, 2, 2, tzinfo=UTC))
    assert historical.iloc[0]["value"] == 20.0
    assert current.iloc[0]["value"] == 21.0


def test_merge_revision_history_keeps_one_copy_of_same_semantic_row() -> None:
    session = pd.Timestamp("2025-01-02")
    row = {
        "series_id": "VIX_CLOSE",
        "session_date": session,
        "value": 20.0,
        "unit": "index_points",
        "source": "CBOE",
        "source_symbol": "VIX",
        "observed_at": "2025-01-02T16:15:00-05:00",
        "available_at": decision_as_of(session).isoformat(),
        "ingested_at": "2025-01-03T13:00:00+00:00",
        "revision_id": "legacy-file-hash",
        "methodology_version": "CBOE_VIX_OFFICIAL_EOD",
        "vintage_kind": "ASSUMED_PIT",
    }
    duplicate = {
        **row,
        "ingested_at": "2025-02-01T15:30:00+00:00",
        "revision_id": "new-row-hash",
    }

    merged = merge_revision_history(
        pd.DataFrame([row]), pd.DataFrame([duplicate]), entity_columns=["series_id"]
    )

    assert merged["revision_id"].tolist() == ["legacy-file-hash"]


def test_historical_selector_uses_effective_time_not_revision_hash_order() -> None:
    session = pd.Timestamp("2025-01-02")
    frame = pd.DataFrame(
        [
            {
                "series_id": "X",
                "session_date": session,
                "available_at": "2025-01-03T13:00:00+00:00",
                "ingested_at": "2025-01-03T13:00:00+00:00",
                "revision_id": "z-old",
                "vintage_kind": "ASSUMED_PIT",
                "value": 1.0,
            },
            {
                "series_id": "X",
                "session_date": session,
                "available_at": "2025-01-03T14:00:00+00:00",
                "ingested_at": "2025-01-03T14:00:00+00:00",
                "revision_id": "a-new",
                "vintage_kind": "ASSUMED_PIT",
                "value": 2.0,
            },
        ]
    )

    selected = select_historical_point_in_time(frame, entity_columns=["series_id"])

    assert selected.iloc[0]["revision_id"] == "a-new"
