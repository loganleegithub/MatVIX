from __future__ import annotations

import os
import shutil
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from conftest import make_observations, make_vx_history

import matvix.daily_update as daily_update
from matvix.calendar import decision_as_of, sessions_in_range
from matvix.daily_update import (
    DailyCandidate,
    DailyUpdateResult,
    DailyUpdateStatus,
    DownloadStatus,
    FreshnessStatus,
    ProjectPublicationBusyError,
    SourceNotReady,
    SourceRefreshResult,
    acceptance_receipt_path,
    assess_source_freshness,
    import_cboe_spx_history_bytes,
    last_good_session,
    latest_common_complete_session,
    load_source_manifest,
    parse_cfe_daily_settlement_csv,
    project_publication_lock,
    read_update_status,
    refresh_official_sources,
    run_daily_update,
    with_snapshot_publication_binding,
)
from matvix.data.cfe import parse_monthly_contract
from matvix.data.point_in_time import merge_revision_history
from matvix.features.futures_curve import select_standard_monthly_curve
from matvix.http_runtime import find_latest_accepted_snapshot
from matvix.pipeline import ProjectPaths
from matvix.storage import read_json, write_json, write_parquet

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = load_source_manifest(PROJECT_ROOT)


def _persist_inputs(
    root: Path, observations: pd.DataFrame, vx_contracts: pd.DataFrame
) -> ProjectPaths:
    paths = ProjectPaths(root)
    shutil.copytree(PROJECT_ROOT / "configs", root / "configs", dirs_exist_ok=True)
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
        probability_contract={"state_history": {"relevant_columns_digest": "sha256:test-state"}},
        cache_action="EXACT_CACHE_HIT",
        acceptance_report={
            "passed": True,
            "session_date": target.date().isoformat(),
            "gates": [],
        },
    )


def _write_bound_receipt(
    paths: ProjectPaths,
    session: pd.Timestamp,
    snapshot_path: Path,
) -> Path:
    return write_json(
        with_snapshot_publication_binding(
            {"session_date": session.date().isoformat(), "passed": True},
            snapshot_path,
        ),
        acceptance_receipt_path(paths, session),
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


@pytest.mark.parametrize(
    ("column", "wrong_value"),
    [
        ("source", "FRED"),
        ("source_symbol", "SP500"),
        ("vintage_kind", "OBSERVED_PIT"),
    ],
)
def test_freshness_rejects_wrong_observation_source_identity(column: str, wrong_value: str) -> None:
    observations, vx, target = _complete_inputs()
    mask = pd.to_datetime(observations["session_date"]).eq(target) & observations["series_id"].eq(
        "SPX_CLOSE"
    )
    observations.loc[mask, column] = wrong_value

    report = assess_source_freshness(observations, vx, MANIFEST, target)
    statuses = {item.series_id: item.status for item in report.sources}

    assert not report.complete
    assert statuses["SPX_CLOSE"] == FreshnessStatus.STALE
    assert (
        report.latest_complete_session
        == sessions_in_range("2025-01-02", target)[-2].date().isoformat()
    )


@pytest.mark.parametrize(
    ("column", "wrong_value"),
    [
        ("source", "CBOE"),
        ("source_symbol", "VX_WEEKLY"),
        ("vintage_kind", "OBSERVED_PIT"),
    ],
)
def test_freshness_rejects_wrong_vx_source_identity(column: str, wrong_value: str) -> None:
    observations, vx, target = _complete_inputs()
    vx.loc[pd.to_datetime(vx["session_date"]).eq(target), column] = wrong_value

    report = assess_source_freshness(observations, vx, MANIFEST, target)
    statuses = {item.series_id: item.status for item in report.sources}

    assert not report.complete
    assert statuses["VX_SETTLE"] == FreshnessStatus.STALE
    assert (
        report.latest_complete_session
        == sessions_in_range("2025-01-02", target)[-2].date().isoformat()
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
        "Q (Aug 2026)",
        "U (Sep 2026)",
        "V (Oct 2026)",
        "X (Nov 2026)",
        "Z (Dec 2026)",
        "F (Jan 2027)",
        "G (Feb 2027)",
    ]
    assert frame["settle"].gt(0).all()
    assert frame["revision_id"].str.startswith("sha256:").all()
    assert frame["available_at"].nunique() == 1
    assert frame.iloc[0]["available_at"] == decision_as_of("2026-08-19").isoformat()


def test_cfe_daily_parser_distinguishes_not_published_from_invalid_price() -> None:
    header_only = b"Product,Symbol,Expiration Date,Price\n"
    invalid_price = b"Product,Symbol,Expiration Date,Price\nVX,VX/U6,2026-09-16,not-a-price\n"

    with pytest.raises(SourceNotReady, match="no published standard-monthly"):
        parse_cfe_daily_settlement_csv(header_only, "2026-08-19")
    with pytest.raises(ValueError, match="invalid standard-monthly VX price"):
        parse_cfe_daily_settlement_csv(invalid_price, "2026-08-19")


def test_cfe_daily_parser_rejects_symbol_expiration_mismatch() -> None:
    wrong_month_code = b"Product,Symbol,Expiration Date,Price\nVX,VX/V6,2026-09-16,17.6066\n"

    with pytest.raises(ValueError, match="symbol/expiration mismatch"):
        parse_cfe_daily_settlement_csv(wrong_month_code, "2026-08-19")


def test_cfe_download_rejects_vendor_fallback_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status_code = 200
        content = b"Product,Symbol,Expiration Date,Price\nVX,VX/U6,2026-09-16,17.6066\n"
        headers = {"Content-Disposition": "attachment; filename=FuturesSettlements_2026-08-19.csv"}

        @staticmethod
        def raise_for_status() -> None:
            return

    monkeypatch.setattr(daily_update.requests, "get", lambda *args, **kwargs: Response())

    with pytest.raises(SourceNotReady, match="fallback is 2026-08-19"):
        daily_update._download_cfe_settlement_bytes(
            daily_update.CFE_DAILY_SETTLEMENT_URL.format(session="2026-08-21"),
            target_session=pd.Timestamp("2026-08-21"),
            timeout=3,
        )


def test_daily_settlement_then_monthly_archive_merges_to_one_canonical_curve(
    tmp_path: Path,
) -> None:
    content = b"""Product,Symbol,Expiration Date,Price
VX,VX/Q6,2026-08-19,15.29
VX,VX/U6,2026-09-16,17.6066
VX,VX/V6,2026-10-21,19.3886
VX,VX/X6,2026-11-18,20.0943
VX,VX/Z6,2026-12-16,20.2988
VX,VX/F7,2027-01-20,21.475
VX,VX/G7,2027-02-17,21.9532
"""
    daily = parse_cfe_daily_settlement_csv(
        content,
        "2026-08-18",
        ingested_at=datetime(2026, 8, 19, 14, 0, tzinfo=UTC),
    )
    archive_path = tmp_path / "VX_2026-09-16.csv"
    archive_path.write_text(
        "Trade Date,Futures,Settle\n08/18/2026,U (Sep 2026),17.6066\n",
        encoding="utf-8",
    )
    archive = parse_monthly_contract(
        archive_path,
        ingested_at=datetime(2026, 8, 20, 14, 0, tzinfo=UTC),
    )

    merged = merge_revision_history(daily, archive, entity_columns=["contract_id"])
    selected = merged.loc[pd.to_datetime(merged["session_date"]).eq(pd.Timestamp("2026-08-18"))]
    curve = select_standard_monthly_curve(merged, "2026-08-18", count=6)

    assert len(merged) == len(daily)
    assert not selected.duplicated(["session_date", "final_settlement_date"]).any()
    assert curve["contract_id"].is_unique
    assert curve["final_settlement_date"].is_unique
    assert len(curve) == 6


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


def test_header_only_cfe_response_is_reported_not_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations, vx, target = _complete_inputs()
    paths = _persist_inputs(tmp_path, observations, vx)
    spx_content = f"DATE,SPX\n{target.strftime('%m/%d/%Y')},6000.00\n".encode("ascii")

    def download(url: str, *, timeout: int) -> bytes:
        assert timeout == 3
        if url == daily_update.CBOE_SPX_HISTORY_URL:
            return spx_content
        raise AssertionError(url)

    def download_cfe(url: str, *, target_session: pd.Timestamp, timeout: int) -> bytes:
        assert url.startswith("https://www-api.cboe.com/")
        assert target_session == target
        assert timeout == 3
        return b"Product,Symbol,Expiration Date,Price\n"

    monkeypatch.setattr(daily_update, "SUPPORTED_SYMBOLS", ())
    monkeypatch.setattr(daily_update, "_download_bytes", download)
    monkeypatch.setattr(daily_update, "_download_cfe_settlement_bytes", download_cfe)

    result = refresh_official_sources(
        paths,
        target,
        decision_as_of(target),
        live_root=tmp_path / "data/raw/live",
        timeout=3,
    )

    cfe_attempt = next(item for item in result.attempts if item.source == "CFE")
    assert cfe_attempt.status == DownloadStatus.NOT_READY
    assert "no published standard-monthly" in str(cfe_attempt.message)
    assert not (tmp_path / f"data/raw/live/cfe/settlement_{target.date()}.csv").exists()


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
    receipt = acceptance_receipt_path(paths, target)
    first_bytes = snapshot.read_bytes()
    first_mtime = snapshot.stat().st_mtime_ns
    first_receipt_mtime = receipt.stat().st_mtime_ns

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
    assert receipt.stat().st_mtime_ns == first_receipt_mtime
    assert receipt.stat().st_mtime_ns >= snapshot.stat().st_mtime_ns
    assert read_json(snapshot)["session_date"] == target.date().isoformat()
    release = read_json(receipt)["release_contract"]
    assert release["probability_artifact_state_digest"] == "sha256:test-state"
    binding = read_json(receipt)["publication_binding"]
    assert binding["binding_version"] == "SNAPSHOT_SHA256_V1"
    assert binding["session_date"] == target.date().isoformat()
    assert binding["snapshot_sha256"].startswith("sha256:")
    assert binding["snapshot_size"] == len(snapshot.read_bytes())
    accepted = find_latest_accepted_snapshot(tmp_path)
    assert accepted is not None and accepted.session_date == target.date().isoformat()


def test_daily_update_migrates_identical_snapshot_from_legacy_unbound_receipt(
    tmp_path: Path,
) -> None:
    observations, vx, target = _complete_inputs()
    paths = _persist_inputs(tmp_path, observations, vx)
    candidate = _candidate(target)
    snapshot = paths.daily_output_dir / f"{target.date()}.json"
    receipt = acceptance_receipt_path(paths, target)
    write_json(candidate.payload, snapshot)
    write_json(candidate.acceptance_report, receipt)
    assert find_latest_accepted_snapshot(tmp_path) is None

    result = run_daily_update(
        tmp_path,
        target,
        now=decision_as_of(target) + timedelta(minutes=5),
        manifest=MANIFEST,
        candidate_builder=lambda *_args: candidate,
    )

    assert result.status == DailyUpdateStatus.PUBLISHED
    assert read_json(receipt)["publication_binding"]["snapshot_sha256"].startswith("sha256:")
    accepted = find_latest_accepted_snapshot(tmp_path)
    assert accepted is not None
    assert accepted.session_date == target.date().isoformat()


def test_overlapping_daily_update_returns_busy_and_releases_lock(
    tmp_path: Path,
) -> None:
    observations, vx, target = _complete_inputs()
    _persist_inputs(tmp_path, observations, vx)
    entered_builder = threading.Event()
    release_builder = threading.Event()
    results: list[DailyUpdateResult] = []

    def blocking_builder(
        _paths: ProjectPaths,
        _observations: pd.DataFrame,
        _vx: pd.DataFrame,
        session: pd.Timestamp,
    ) -> DailyCandidate:
        entered_builder.set()
        if not release_builder.wait(timeout=5):
            raise TimeoutError("test did not release candidate builder")
        return _candidate(session)

    worker = threading.Thread(
        target=lambda: results.append(
            run_daily_update(
                tmp_path,
                target,
                now=decision_as_of(target) + timedelta(minutes=5),
                manifest=MANIFEST,
                candidate_builder=blocking_builder,
            )
        )
    )
    worker.start()
    try:
        assert entered_builder.wait(timeout=5)
        busy = run_daily_update(
            tmp_path,
            target,
            now=decision_as_of(target) + timedelta(minutes=6),
            manifest=MANIFEST,
            candidate_builder=lambda *_args: _candidate(target),
        )
        assert busy.status == DailyUpdateStatus.BUSY
        assert "publication lock" in busy.message
    finally:
        release_builder.set()
        worker.join(timeout=5)

    assert not worker.is_alive()
    assert [result.status for result in results] == [DailyUpdateStatus.PUBLISHED]
    after_release = run_daily_update(
        tmp_path,
        target,
        now=decision_as_of(target) + timedelta(minutes=7),
        manifest=MANIFEST,
        candidate_builder=lambda *_args: _candidate(target),
    )
    assert after_release.status == DailyUpdateStatus.ALREADY_CURRENT
    status = read_update_status(tmp_path)
    assert status is not None
    assert status["last_good_session"] == target.date().isoformat()
    assert status["sources"] == status["data_sources"]


def test_publication_lock_context_is_shared_nonblocking_and_reusable(tmp_path: Path) -> None:
    target = pd.Timestamp("2025-01-15")
    current = decision_as_of(target) + timedelta(minutes=5)

    with project_publication_lock(tmp_path, target, current=current):
        with pytest.raises(ProjectPublicationBusyError, match="project lock"):
            with project_publication_lock(tmp_path, target, current=current):
                raise AssertionError("busy publication lock must not be entered")

    with project_publication_lock(tmp_path, target, current=current):
        pass


def test_unchanged_snapshot_rewrites_a_missing_or_stale_acceptance_receipt(
    tmp_path: Path,
) -> None:
    observations, vx, target = _complete_inputs()
    paths = _persist_inputs(tmp_path, observations, vx)
    now = decision_as_of(target) + timedelta(minutes=5)

    def builder(
        _paths: ProjectPaths,
        _observations: pd.DataFrame,
        _vx: pd.DataFrame,
        session: pd.Timestamp,
    ) -> DailyCandidate:
        return _candidate(session)

    first = run_daily_update(
        tmp_path,
        target,
        now=now,
        manifest=MANIFEST,
        candidate_builder=builder,
    )
    snapshot = paths.daily_output_dir / f"{target.date()}.json"
    receipt = acceptance_receipt_path(paths, target)
    stale_mtime = max(0, snapshot.stat().st_mtime_ns - 1)
    os.utime(receipt, ns=(stale_mtime, stale_mtime))
    assert receipt.stat().st_mtime_ns < snapshot.stat().st_mtime_ns

    second = run_daily_update(
        tmp_path,
        target,
        now=now + timedelta(minutes=1),
        manifest=MANIFEST,
        candidate_builder=builder,
    )

    assert first.status == DailyUpdateStatus.PUBLISHED
    assert second.status == DailyUpdateStatus.PUBLISHED
    assert receipt.stat().st_mtime_ns >= snapshot.stat().st_mtime_ns
    accepted = find_latest_accepted_snapshot(tmp_path)
    assert accepted is not None and accepted.session_date == target.date().isoformat()


def test_receipt_failure_leaves_new_snapshot_unauthorized_and_preserves_last_good(
    tmp_path: Path,
) -> None:
    observations, vx, target = _complete_inputs()
    paths = _persist_inputs(tmp_path, observations, vx)
    prior = sessions_in_range("2025-01-02", target.date())[-2]
    prior_snapshot = paths.daily_output_dir / f"{prior.date()}.json"
    write_json(
        {
            "session_date": prior.date().isoformat(),
            "data_status": "OK",
            "issues": [],
        },
        prior_snapshot,
    )
    _write_bound_receipt(paths, prior, prior_snapshot)

    def fail_receipt(_: dict[str, object], __: str | Path) -> Path:
        raise OSError("simulated receipt failure")

    result = run_daily_update(
        tmp_path,
        target,
        now=decision_as_of(target) + timedelta(minutes=5),
        manifest=MANIFEST,
        candidate_builder=lambda _paths, _observations, _vx, session: _candidate(session),
        receipt_writer=fail_receipt,
    )

    target_snapshot = paths.daily_output_dir / f"{target.date()}.json"
    assert result.status == DailyUpdateStatus.FAILED
    assert result.last_good_session == prior.date().isoformat()
    assert target_snapshot.exists()
    assert not acceptance_receipt_path(paths, target).exists()
    assert last_good_session(paths) == prior.date().isoformat()
    accepted = find_latest_accepted_snapshot(tmp_path)
    assert accepted is not None and accepted.session_date == prior.date().isoformat()


def test_daily_update_failure_preserves_prior_last_good(tmp_path: Path) -> None:
    observations, vx, target = _complete_inputs()
    paths = _persist_inputs(tmp_path, observations, vx)
    prior = sessions_in_range("2025-01-02", target.date())[-2]
    prior_path = paths.daily_output_dir / f"{prior.date()}.json"
    write_json(
        {"session_date": prior.date().isoformat(), "data_status": "OK", "issues": []},
        prior_path,
    )
    _write_bound_receipt(paths, prior, prior_path)
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
