from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
from conftest import make_observations, make_vx_history

from matvix.calendar import decision_as_of, sessions_in_range
from matvix.daily_update import (
    DailyCandidate,
    DailyUpdateStatus,
    FreshnessStatus,
    SourceRefreshResult,
    assess_source_freshness,
    import_cboe_spx_history_bytes,
    latest_common_complete_session,
    load_source_manifest,
    parse_cfe_daily_settlement_csv,
    read_update_status,
    run_daily_update,
)
from matvix.pipeline import ProjectPaths
from matvix.storage import read_json, write_json, write_parquet

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = load_source_manifest(PROJECT_ROOT)


def _persist_inputs(
    root: Path, observations: pd.DataFrame, vx_contracts: pd.DataFrame
) -> ProjectPaths:
    paths = ProjectPaths(root)
    write_parquet(observations, paths.observations)
    write_parquet(vx_contracts, paths.vx_contracts)
    return paths


def _complete_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    observations = make_observations("2025-01-02", "2025-01-15")
    sessions = pd.DatetimeIndex(sorted(pd.to_datetime(observations["session_date"]).unique()))
    return observations, make_vx_history(sessions), sessions[-1]


def _candidate(target: pd.Timestamp) -> DailyCandidate:
    payload = {
        "session_date": target.date().isoformat(),
        "data_status": "OK",
        "input_manifest_hash": "sha256:test",
        "issues": [],
    }
    return DailyCandidate(
        payload=payload,
        metadata={"prediction_date": target.date().isoformat()},
        features=pd.DataFrame({"session_date": [target], "feature": [1.0]}),
        states=pd.DataFrame({"session_date": [target], "data_status": ["OK"], "phase": ["TEST"]}),
        targets=pd.DataFrame(),
        oof=pd.DataFrame(),
        probability_contract={},
        cache_action="EXACT_CACHE_HIT",
        acceptance_report={"passed": True},
    )


def test_freshness_requires_all_manifest_series_and_a_complete_vx_curve() -> None:
    observations, vx, target = _complete_inputs()
    report = assess_source_freshness(observations, vx, MANIFEST, target)

    assert report.complete
    assert report.latest_complete_session == target.date().isoformat()
    assert latest_common_complete_session(observations, vx, MANIFEST) == target

    without_skew = observations.loc[
        ~(
            pd.to_datetime(observations["session_date"]).eq(target)
            & observations["series_id"].eq("SKEW_CLOSE")
        )
    ]
    without_target_vx = vx.loc[~pd.to_datetime(vx["session_date"]).eq(target)]
    stale = assess_source_freshness(without_skew, without_target_vx, MANIFEST, target)
    statuses = {item.series_id: item.status for item in stale.sources}

    assert not stale.complete
    assert statuses["SKEW_CLOSE"] == FreshnessStatus.STALE
    assert statuses["VX_SETTLE"] == FreshnessStatus.STALE
    assert (
        stale.latest_complete_session
        == sessions_in_range("2025-01-02", target.date())[-2].date().isoformat()
    )


def test_cfe_daily_parser_keeps_only_standard_monthly_vx_contracts() -> None:
    content = b"""Product,Symbol,Expiration Date,Price
VX,VX/Q6,2026-08-19,15.29
VX,VX34/Q6,2026-08-26,17.6066
VX,VX/U6,2026-09-16,17.6066
VX,VX/V6,2026-10-21,19.3886
VX,VX/X6,2026-11-18,20.0943
VX,VX/Z6,2026-12-16,20.2988
VX,VX/F7,2027-01-20,21.475
VX,VX/G7,2027-02-17,21.9532*
VXM,VXM/U6,2026-09-16,17.6066
"""

    frame = parse_cfe_daily_settlement_csv(
        content,
        "2026-08-19",
        ingested_at=datetime(2026, 8, 20, 13, 0, tzinfo=UTC),
    )

    assert frame["contract_id"].tolist() == [
        "VX/Q6",
        "VX/U6",
        "VX/V6",
        "VX/X6",
        "VX/Z6",
        "VX/F7",
        "VX/G7",
    ]
    assert frame["settle"].gt(0).all()
    assert frame["revision_id"].str.startswith("sha256:").all()
    assert frame["available_at"].nunique() == 1
    assert frame.iloc[0]["available_at"] == decision_as_of("2026-08-19").isoformat()


def test_spx_import_filters_pre_project_history_before_pit_conversion() -> None:
    content = b"""DATE,SPX
01/02/1975,70.23
12/31/2012,1426.19
01/02/2013,1462.42
01/03/2013,1459.37
01/05/2013,9999.00
"""

    frame = import_cboe_spx_history_bytes(
        content,
        start_session="2013-01-02",
        end_session="2013-01-04",
        ingested_at=datetime(2026, 8, 20, tzinfo=UTC),
    )

    assert frame["session_date"].astype(str).tolist() == ["2013-01-02", "2013-01-03"]
    assert frame["series_id"].eq("SPX_CLOSE").all()
    assert frame["source"].eq("CBOE").all()


def test_daily_update_prefetches_but_never_publishes_before_decision_time(
    tmp_path: Path,
) -> None:
    observations, vx, target = _complete_inputs()
    paths = _persist_inputs(tmp_path, observations, vx)
    refresh_calls: list[pd.Timestamp] = []

    def refresh(_: ProjectPaths, session: pd.Timestamp, __: datetime) -> SourceRefreshResult:
        refresh_calls.append(session)
        return SourceRefreshResult()

    def forbidden_builder(
        _: ProjectPaths, __: pd.DataFrame, ___: pd.DataFrame, ____: pd.Timestamp
    ) -> DailyCandidate:
        raise AssertionError("candidate must not be built before 09:20 America/New_York")

    before_due = decision_as_of(target) - timedelta(minutes=1)
    result = run_daily_update(
        tmp_path,
        target,
        now=before_due,
        refresh=refresh,
        manifest=MANIFEST,
        candidate_builder=forbidden_builder,
    )

    assert result.status == DailyUpdateStatus.NOT_DUE
    assert refresh_calls == [target]
    assert result.next_check_at == decision_as_of(target).astimezone(UTC).isoformat()
    assert not (paths.daily_output_dir / f"{target.date()}.json").exists()


def test_daily_update_is_idempotent_for_an_identical_accepted_candidate(tmp_path: Path) -> None:
    observations, vx, target = _complete_inputs()
    paths = _persist_inputs(tmp_path, observations, vx)
    now = decision_as_of(target) + timedelta(minutes=5)
    calls = 0

    def builder(
        _: ProjectPaths, __: pd.DataFrame, ___: pd.DataFrame, session: pd.Timestamp
    ) -> DailyCandidate:
        nonlocal calls
        calls += 1
        return _candidate(session)

    first = run_daily_update(
        tmp_path,
        target,
        now=now,
        manifest=MANIFEST,
        candidate_builder=builder,
    )
    snapshot = paths.daily_output_dir / f"{target.date()}.json"
    first_bytes = snapshot.read_bytes()
    first_mtime = snapshot.stat().st_mtime_ns

    second = run_daily_update(
        tmp_path,
        target,
        now=now + timedelta(minutes=1),
        manifest=MANIFEST,
        candidate_builder=builder,
    )

    assert first.status == DailyUpdateStatus.PUBLISHED
    assert second.status == DailyUpdateStatus.ALREADY_CURRENT
    assert calls == 2
    assert snapshot.read_bytes() == first_bytes
    assert snapshot.stat().st_mtime_ns == first_mtime
    assert read_json(snapshot)["session_date"] == target.date().isoformat()
    status = read_update_status(tmp_path)
    assert status is not None
    assert status["last_good_session"] == target.date().isoformat()
    assert status["sources"] == status["data_sources"]


def test_daily_update_failure_preserves_prior_last_good(tmp_path: Path) -> None:
    observations, vx, target = _complete_inputs()
    paths = _persist_inputs(tmp_path, observations, vx)
    prior = sessions_in_range("2025-01-02", target.date())[-2]
    prior_path = paths.daily_output_dir / f"{prior.date()}.json"
    write_json(
        {"session_date": prior.date().isoformat(), "data_status": "OK", "issues": []},
        prior_path,
    )
    prior_bytes = prior_path.read_bytes()

    def failing_builder(
        _: ProjectPaths, __: pd.DataFrame, ___: pd.DataFrame, ____: pd.Timestamp
    ) -> DailyCandidate:
        raise RuntimeError("simulated probability failure")

    result = run_daily_update(
        tmp_path,
        target,
        now=decision_as_of(target) + timedelta(minutes=5),
        manifest=MANIFEST,
        candidate_builder=failing_builder,
    )

    assert result.status == DailyUpdateStatus.FAILED
    assert result.last_good_session == prior.date().isoformat()
    assert prior_path.read_bytes() == prior_bytes
    assert not (paths.daily_output_dir / f"{target.date()}.json").exists()
    assert "last-good preserved" in result.message


def test_daily_update_does_not_build_when_latest_common_session_is_stale(
    tmp_path: Path,
) -> None:
    observations, vx, target = _complete_inputs()
    vx = vx.loc[~pd.to_datetime(vx["session_date"]).eq(target)]
    _persist_inputs(tmp_path, observations, vx)

    def forbidden_builder(
        _: ProjectPaths, __: pd.DataFrame, ___: pd.DataFrame, ____: pd.Timestamp
    ) -> DailyCandidate:
        raise AssertionError("stale sources must not build a candidate")

    result = run_daily_update(
        tmp_path,
        target,
        now=decision_as_of(target) + timedelta(minutes=5),
        manifest=MANIFEST,
        candidate_builder=forbidden_builder,
    )

    assert result.status == DailyUpdateStatus.SOURCES_PENDING
    assert result.sources["VX_SETTLE"]["status"] == FreshnessStatus.STALE.value
