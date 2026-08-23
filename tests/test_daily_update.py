from __future__ import annotations

import hashlib
import os
import shutil
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from conftest import make_observations, make_vx_history

import matvix.daily_update as daily_update
from matvix.calendar import add_sessions, decision_as_of, sessions_in_range
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
    import_release_source_generation,
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
from matvix.prospective import ActivationIdentity, prediction_record_path
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


def _release_generation_fixture(root: Path) -> tuple[Path, Path]:
    live = root / "live"
    cboe = live / "cboe"
    cfe = live / "cfe"
    cboe.mkdir(parents=True)
    cfe.mkdir(parents=True)
    session = "2025-01-16"
    files: dict[str, dict[str, str]] = {}
    for symbol in ("VIX", "VIX9D", "VIX3M", "VIX6M", "VVIX", "SKEW"):
        relative = f"cboe/{symbol}_History.csv"
        content = (
            f"DATE,OPEN,HIGH,LOW,CLOSE\n{session},18,20,17,19\n"
            if symbol == "VIX"
            else f"DATE,CLOSE\n{session},19\n"
        ).encode()
        target = live / relative
        target.write_bytes(content)
        files[relative] = {
            "kind": "CBOE_INDEX_HISTORY",
            "symbol": symbol,
            "ingested_at": "2025-01-17T14:30:00+00:00",
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    spx_relative = "cboe/SPX_History.csv"
    spx_content = f"DATE,SPX\n{session},6000\n".encode()
    (live / spx_relative).write_bytes(spx_content)
    files[spx_relative] = {
        "kind": "CBOE_SPX_HISTORY",
        "ingested_at": "2025-01-17T14:30:00+00:00",
        "sha256": hashlib.sha256(spx_content).hexdigest(),
    }
    cfe_relative = f"cfe/settlement_{session}.csv"
    cfe_content = b"""Product,Symbol,Expiration Date,Price
VX,VX/F5,2025-01-22,15.0
VX,VX/G5,2025-02-19,16.0
VX,VX/H5,2025-03-18,17.0
VX,VX/J5,2025-04-16,18.0
VX,VX/K5,2025-05-21,19.0
VX,VX/M5,2025-06-18,20.0
VX,VX/N5,2025-07-16,21.0
"""
    (live / cfe_relative).write_bytes(cfe_content)
    files[cfe_relative] = {
        "kind": "CFE_DAILY_SETTLEMENT",
        "session_date": session,
        "ingested_at": "2025-01-17T14:30:00+00:00",
        "sha256": hashlib.sha256(cfe_content).hexdigest(),
    }
    manifest = root / "release_generation.json"
    write_json(
        {
            "manifest_version": "1.0.0",
            "generation_id": "TEST_RELEASE_GENERATION",
            "latest_session": session,
            "files": files,
        },
        manifest,
    )
    write_json(
        {
            "authorized_data_requirement": {
                "live_generation_manifest_entries": len(files),
                "live_generation_manifest_sha256": hashlib.sha256(
                    manifest.read_bytes()
                ).hexdigest(),
            }
        },
        root / "MATVIX_V3_RELEASE_MANIFEST.json",
    )
    return live, manifest


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


def _prospective_candidate(
    target: pd.Timestamp, *, candidate_probability: float = 0.31
) -> DailyCandidate:
    candidate = _candidate(target)
    events: dict[str, dict[str, object]] = {}
    metadata: dict[str, object] = {}
    for event_id, horizon in {
        "acute_front_stress_5d": 5,
        "front_inversion_5d": 5,
        "mid_curve_pressure_accelerates_5d": 5,
        "broad_stress_persists_10d": 10,
        "carry_environment_recovers_10d": 10,
    }.items():
        broad = event_id == "broad_stress_persists_10d"
        valid = add_sessions(target, horizon).date().isoformat()
        events[event_id] = {
            "event_status": "ELIGIBLE",
            "model_status": "BASE_RATE_ONLY" if broad else "CALIBRATED_MODEL",
            "probability_kind": "HISTORICAL_REFERENCE" if broad else "FEATURE_CONDITIONAL",
            "probability": 0.2 if broad else 0.3,
            "base_rate": 0.2,
            "valid_through_session": valid,
        }
        metadata[event_id] = (
            {"publication_policy": "BASE_RATE_ONLY_EXEMPT"}
            if broad
            else {
                "publication_method": "ROLLING_INTERCEPT_252",
                "candidate_probability": candidate_probability,
            }
        )
    payload = {
        **candidate.payload,
        "decision_as_of": decision_as_of(target).isoformat(),
        "probability_judgment": events,
    }
    return replace(candidate, payload=payload, metadata=metadata)


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


def test_release_source_generation_is_verified_complete_and_idempotent(tmp_path: Path) -> None:
    observations, vx, _ = _complete_inputs()
    paths = _persist_inputs(tmp_path, observations, vx)
    live, manifest = _release_generation_fixture(tmp_path)

    first = import_release_source_generation(
        paths,
        live_root=live,
        manifest_path=manifest,
    )
    second = import_release_source_generation(
        paths,
        live_root=live,
        manifest_path=manifest,
    )

    assert first["verified_files"] == 8
    assert first["added_observations"] == 10
    assert first["added_vx_rows"] == 7
    assert second["added_observations"] == 0
    assert second["added_vx_rows"] == 0


def test_release_source_generation_rejects_file_hash_drift(tmp_path: Path) -> None:
    observations, vx, _ = _complete_inputs()
    paths = _persist_inputs(tmp_path, observations, vx)
    live, manifest = _release_generation_fixture(tmp_path)
    (live / "cboe" / "VIX_History.csv").write_bytes(b"changed")

    with pytest.raises(ValueError, match="sha256 mismatch: cboe/VIX_History.csv"):
        import_release_source_generation(
            paths,
            live_root=live,
            manifest_path=manifest,
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
    curve = select_standard_monthly_curve(merged, "2026-08-18", count=7)

    assert len(merged) == len(daily)
    assert not selected.duplicated(["session_date", "final_settlement_date"]).any()
    assert curve["contract_id"].is_unique
    assert curve["final_settlement_date"].is_unique
    assert len(curve) == 7


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


def _activated_identity() -> ActivationIdentity:
    return ActivationIdentity(
        activated=True,
        capture_ready=True,
        activation_commit="b" * 40,
        head_commit="c" * 40,
        reason="ACTIVE_CLEAN_RELEASE",
    )


def test_activated_daily_update_writes_prediction_before_bound_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observations, vx, target = _complete_inputs()
    paths = _persist_inputs(tmp_path, observations, vx)
    now = decision_as_of(target) + timedelta(minutes=5)
    monkeypatch.setattr(daily_update, "activation_identity", lambda _root: _activated_identity())

    first = run_daily_update(
        tmp_path,
        target,
        now=now,
        manifest=MANIFEST,
        candidate_builder=lambda *_args: _prospective_candidate(target),
    )
    prediction = prediction_record_path(tmp_path, target.date().isoformat())
    receipt_path = acceptance_receipt_path(paths, target)
    receipt = read_json(receipt_path)

    assert first.status == DailyUpdateStatus.PUBLISHED
    assert prediction.exists()
    assert receipt["prospective_evidence"]["status"] == "LOCAL_CAPTURED"
    assert receipt["prospective_evidence"]["prediction"]["sha256"].startswith("sha256:")
    assert receipt_path.stat().st_mtime_ns >= prediction.stat().st_mtime_ns
    assert find_latest_accepted_snapshot(tmp_path) is not None

    prediction_mtime = prediction.stat().st_mtime_ns
    receipt_mtime = receipt_path.stat().st_mtime_ns
    second = run_daily_update(
        tmp_path,
        target,
        now=now + timedelta(minutes=1),
        manifest=MANIFEST,
        candidate_builder=lambda *_args: _prospective_candidate(target),
    )
    assert second.status == DailyUpdateStatus.ALREADY_CURRENT
    assert prediction.stat().st_mtime_ns == prediction_mtime
    assert receipt_path.stat().st_mtime_ns == receipt_mtime


def test_receipt_failure_recovers_orphan_prediction_idempotently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observations, vx, target = _complete_inputs()
    paths = _persist_inputs(tmp_path, observations, vx)
    now = decision_as_of(target) + timedelta(minutes=5)
    monkeypatch.setattr(daily_update, "activation_identity", lambda _root: _activated_identity())

    def fail_receipt(_: dict[str, object], __: str | Path) -> Path:
        raise OSError("simulated receipt failure")

    failed = run_daily_update(
        tmp_path,
        target,
        now=now,
        manifest=MANIFEST,
        candidate_builder=lambda *_args: _prospective_candidate(target),
        receipt_writer=fail_receipt,
    )
    prediction = prediction_record_path(tmp_path, target.date().isoformat())
    original_prediction = prediction.read_bytes()
    assert failed.status == DailyUpdateStatus.FAILED
    assert not acceptance_receipt_path(paths, target).exists()

    recovered = run_daily_update(
        tmp_path,
        target,
        now=now + timedelta(minutes=1),
        manifest=MANIFEST,
        candidate_builder=lambda *_args: _prospective_candidate(target),
    )
    assert recovered.status == DailyUpdateStatus.PUBLISHED
    assert prediction.read_bytes() == original_prediction
    assert read_json(acceptance_receipt_path(paths, target))["prospective_evidence"][
        "status"
    ] == "LOCAL_CAPTURED"


def test_capture_gap_is_published_degraded_evidence_and_never_backfilled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observations, vx, target = _complete_inputs()
    paths = _persist_inputs(tmp_path, observations, vx)
    now = decision_as_of(target) + timedelta(minutes=5)
    monkeypatch.setattr(daily_update, "activation_identity", lambda _root: _activated_identity())

    def fail_capture(**_kwargs: object) -> object:
        raise OSError("simulated evidence filesystem failure")

    monkeypatch.setattr(daily_update, "capture_prediction_record", fail_capture)
    first = run_daily_update(
        tmp_path,
        target,
        now=now,
        manifest=MANIFEST,
        candidate_builder=lambda *_args: _prospective_candidate(target),
    )
    receipt_path = acceptance_receipt_path(paths, target)
    first_receipt = receipt_path.read_bytes()
    receipt = read_json(receipt_path)
    assert first.status == DailyUpdateStatus.PUBLISHED
    assert receipt["prospective_evidence"] == {
        "schema_version": "1.0.0",
        "status": "EVIDENCE_CAPTURE_GAP",
        "scientific_cohort_id": "MATVIX_V3_0_1_CORE",
        "activation_tag": "matvix-prospective-001-activation",
        "activation_commit": "b" * 40,
        "runtime_release_id": "git:" + "c" * 40,
        "captured_at": now.astimezone(UTC).isoformat(),
        "prediction": None,
        "capture_error": "OSError",
    }
    assert find_latest_accepted_snapshot(tmp_path) is not None
    assert not prediction_record_path(tmp_path, target.date().isoformat()).exists()

    def forbidden_capture(**_kwargs: object) -> object:
        raise AssertionError("a receipt-backed gap must never be backfilled")

    monkeypatch.setattr(daily_update, "capture_prediction_record", forbidden_capture)
    second = run_daily_update(
        tmp_path,
        target,
        now=now + timedelta(minutes=1),
        manifest=MANIFEST,
        candidate_builder=lambda *_args: _prospective_candidate(target),
    )
    assert second.status == DailyUpdateStatus.ALREADY_CURRENT
    assert receipt_path.read_bytes() == first_receipt
    assert not prediction_record_path(tmp_path, target.date().isoformat()).exists()


def test_same_session_changed_snapshot_cannot_overwrite_prediction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observations, vx, target = _complete_inputs()
    paths = _persist_inputs(tmp_path, observations, vx)
    now = decision_as_of(target) + timedelta(minutes=5)
    monkeypatch.setattr(daily_update, "activation_identity", lambda _root: _activated_identity())

    first_candidate = _prospective_candidate(target, candidate_probability=0.31)
    first = run_daily_update(
        tmp_path,
        target,
        now=now,
        manifest=MANIFEST,
        candidate_builder=lambda *_args: first_candidate,
    )
    prediction = prediction_record_path(tmp_path, target.date().isoformat())
    original_prediction = prediction.read_bytes()
    changed_candidate = _prospective_candidate(target, candidate_probability=0.32)
    changed_candidate.payload["probability_judgment"]["acute_front_stress_5d"][
        "probability"
    ] = 0.32
    second = run_daily_update(
        tmp_path,
        target,
        now=now + timedelta(minutes=1),
        manifest=MANIFEST,
        candidate_builder=lambda *_args: changed_candidate,
    )

    assert first.status == DailyUpdateStatus.PUBLISHED
    assert second.status == DailyUpdateStatus.PUBLISHED
    assert prediction.read_bytes() == original_prediction
    receipt = read_json(acceptance_receipt_path(paths, target))
    assert receipt["prospective_evidence"]["status"] == "EVIDENCE_CAPTURE_GAP"
    assert receipt["prospective_evidence"]["capture_error"] == "ProspectiveConflictError"


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
