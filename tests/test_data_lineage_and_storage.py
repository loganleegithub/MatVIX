from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from conftest import make_curve, make_observations

from matvix.data.assemble import daily_vintage_summary, observations_to_wide
from matvix.features.builder import build_feature_table
from matvix.storage import write_json, write_parquet


def _observed_curve_history(sessions: pd.Series) -> pd.DataFrame:
    return pd.concat(
        [make_curve(session, vintage_kind="OBSERVED_PIT") for session in sessions],
        ignore_index=True,
    )


def test_feature_lineage_inherits_assumed_pit_across_d5_and_rolling_inputs() -> None:
    observations = make_observations("2025-01-02", "2025-03-31", vintage_kind="OBSERVED_PIT")
    first_session = pd.to_datetime(observations["session_date"]).min()
    observations.loc[
        pd.to_datetime(observations["session_date"]).eq(first_session), "vintage_kind"
    ] = "ASSUMED_PIT"
    wide = observations_to_wide(observations)
    summary = daily_vintage_summary(observations)
    curves = _observed_curve_history(wide["session_date"])

    features = build_feature_table(wide, curves, summary)
    mature = features.iloc[30]

    assert mature["feature_vintage_kind"] == "ASSUMED_PIT"
    assert mature["pit_evidence"] == "ASSUMED"
    assert bool(mature["formal_vintage_eligible"])


def test_feature_lineage_marks_research_input_in_prior_dependency() -> None:
    observations = make_observations("2025-01-02", "2025-03-31", vintage_kind="OBSERVED_PIT")
    first_session = pd.to_datetime(observations["session_date"]).min()
    observations.loc[
        pd.to_datetime(observations["session_date"]).eq(first_session), "vintage_kind"
    ] = "PROVIDER_BACKTESTED"
    wide = observations_to_wide(observations)
    summary = daily_vintage_summary(observations)
    curves = _observed_curve_history(wide["session_date"])

    features = build_feature_table(wide, curves, summary)
    mature = features.iloc[30]

    assert mature["feature_vintage_kind"] == "PROVIDER_BACKTESTED"
    assert mature["pit_evidence"] == "RESEARCH_ONLY"
    assert not bool(mature["formal_vintage_eligible"])


def test_builder_exposes_methodology_signature_and_front_curve_vintage() -> None:
    observations = make_observations("2025-01-02", "2025-01-10", vintage_kind="OBSERVED_PIT")
    wide = observations_to_wide(observations)
    summary = daily_vintage_summary(observations)
    curves = _observed_curve_history(wide["session_date"])

    features = build_feature_table(wide, curves, summary)

    assert features["feature_methodology_signature"].notna().all()
    assert features["front_curve_formal_vintage_eligible"].all()
    curves.loc[curves["contract_id"].eq("VX_TEST_1"), "vintage_kind"] = "PROVIDER_BACKTESTED"
    changed = build_feature_table(wide, curves, summary)
    assert not changed["front_curve_formal_vintage_eligible"].any()


def test_methodology_change_restarts_cross_day_feature_regime() -> None:
    observations = make_observations("2025-01-02", "2025-03-31", vintage_kind="OBSERVED_PIT")
    sessions = sorted(pd.to_datetime(observations["session_date"]).unique())
    observations.loc[
        pd.to_datetime(observations["session_date"]).ge(sessions[30]),
        "methodology_version",
    ] = "TEST_V2"
    wide = observations_to_wide(observations)
    summary = daily_vintage_summary(observations)
    curves = _observed_curve_history(wide["session_date"])

    features = build_feature_table(wide, curves, summary)

    assert (
        features.loc[29, "feature_methodology_signature"]
        != features.loc[30, "feature_methodology_signature"]
    )
    assert pd.isna(features.loc[30, "d5_log_vix"])
    assert pd.isna(features.loc[30, "vix_ema20"])
    assert not pd.isna(features.loc[55, "vix_ema20"])


def test_single_series_data_gap_does_not_restart_unrelated_feature_warmups() -> None:
    clean = make_observations("2024-01-02", "2025-04-30", vintage_kind="OBSERVED_PIT")
    sessions = sorted(pd.to_datetime(clean["session_date"]).unique())
    gap_session = pd.Timestamp(sessions[270])
    gapped = clean.loc[
        ~(
            pd.to_datetime(clean["session_date"]).eq(gap_session)
            & clean["series_id"].eq("SKEW_CLOSE")
        )
    ].copy()
    curves = _observed_curve_history(pd.Series(sessions))

    clean_features = build_feature_table(
        observations_to_wide(clean), curves, daily_vintage_summary(clean)
    )
    gapped_features = build_feature_table(
        observations_to_wide(gapped), curves, daily_vintage_summary(gapped)
    )
    after_gap = 271

    assert (
        gapped_features.loc[270, "feature_methodology_signature"]
        == clean_features.loc[270, "feature_methodology_signature"]
    )
    assert gapped_features.loc[after_gap, "vix_ema20"] == pytest.approx(
        clean_features.loc[after_gap, "vix_ema20"]
    )
    assert gapped_features.loc[after_gap, "rv_forecast_ewma94"] == pytest.approx(
        clean_features.loc[after_gap, "rv_forecast_ewma94"]
    )
    assert pd.isna(gapped_features.loc[270, "d5_skew"])
    assert pd.isna(gapped_features.loc[275, "d5_skew"])


def test_write_json_preserves_old_target_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "state.json"
    target.write_text('{"old": true}\n', encoding="utf-8")

    def fail_replace(source: str | Path, destination: str | Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr("matvix.storage.os.replace", fail_replace)
    with pytest.raises(OSError, match="simulated"):
        write_json({"new": True}, target)

    assert json.loads(target.read_text(encoding="utf-8")) == {"old": True}
    assert list(tmp_path.iterdir()) == [target]


def test_write_parquet_preserves_old_target_after_partial_temp_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "data.parquet"
    target.write_bytes(b"old-parquet")

    def partial_then_fail(self: pd.DataFrame, path: str | Path, **_: object) -> None:
        Path(path).write_bytes(b"partial")
        raise RuntimeError("simulated parquet failure")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", partial_then_fail)
    with pytest.raises(RuntimeError, match="simulated"):
        write_parquet(pd.DataFrame({"x": [1]}), target)

    assert target.read_bytes() == b"old-parquet"
    assert list(tmp_path.iterdir()) == [target]
