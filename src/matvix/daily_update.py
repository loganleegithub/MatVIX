from __future__ import annotations

import fcntl
import hashlib
import io
import json
import os
import re
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, TextIO, cast

import numpy as np
import pandas as pd
import requests
import yaml

from matvix.acceptance import (
    build_real_acceptance_report,
    failed_gate_names,
    write_real_acceptance_report,
)
from matvix.calendar import (
    NY,
    decision_as_of,
    final_settlement_timestamp,
    is_session,
    observed_at_eod,
    sessions_in_range,
    vix_final_settlement_date,
)
from matvix.config_contract import validate_frozen_config
from matvix.constants import DataStatus
from matvix.data.assemble import REQUIRED_CORE_SERIES
from matvix.data.cboe import (
    CBOE_HISTORY_URL,
    SUPPORTED_SYMBOLS,
    download_cboe_history,
    import_cboe_history,
)
from matvix.data.point_in_time import (
    content_revision_id,
    merge_revision_history,
    select_historical_point_in_time,
)
from matvix.data.spx import import_spx_close
from matvix.features.futures_curve import (
    select_standard_monthly_curve,
    standard_monthly_curve_is_complete,
)
from matvix.pipeline import (
    ProjectPaths,
    build_snapshot_payload,
    build_state_history,
    persist_probability_artifacts,
    persist_snapshot,
    resolve_persisted_probability_artifacts,
)
from matvix.source_identity import (
    OFFICIAL_SOURCE_IDENTITIES,
    SourceIdentity,
    admit_official_observations,
    admit_official_vx_settlements,
)
from matvix.storage import read_json, read_parquet, write_json, write_parquet

CFE_DAILY_SETTLEMENT_URL = (
    "https://www-api.cboe.com/us/futures/market_statistics/settlement/csv?dt={session}"
)
CBOE_SPX_HISTORY_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/SPX_History.csv"
SOURCE_MANIFEST_POLICY = "NEXT_COMMON_SESSION_0920_ET"
RUNTIME_STATUS_RELATIVE_PATH = Path("outputs/runtime/update_status.json")
DAILY_UPDATE_LOCK_RELATIVE_PATH = Path("outputs/runtime/daily-update.lock")
PUBLICATION_BINDING_VERSION = "SNAPSHOT_SHA256_V1"
VX_MONTH_CODES = {
    1: "F",
    2: "G",
    3: "H",
    4: "J",
    5: "K",
    6: "M",
    7: "N",
    8: "Q",
    9: "U",
    10: "V",
    11: "X",
    12: "Z",
}
VX_MONTH_NAMES = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}


class FreshnessStatus(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    MISSING = "MISSING"
    SESSION_GAP = "SESSION_GAP"
    INCOMPLETE = "INCOMPLETE"


class DownloadStatus(StrEnum):
    UPDATED = "UPDATED"
    UNCHANGED = "UNCHANGED"
    REUSED_LAST_SUCCESS = "REUSED_LAST_SUCCESS"
    NOT_READY = "NOT_READY"
    FAILED = "FAILED"


class DailyUpdateStatus(StrEnum):
    BUSY = "BUSY"
    NOT_DUE = "NOT_DUE"
    SOURCES_PENDING = "SOURCES_PENDING"
    PUBLISHED = "PUBLISHED"
    ALREADY_CURRENT = "ALREADY_CURRENT"
    FAILED = "FAILED"
    WINDOW_EXHAUSTED = "WINDOW_EXHAUSTED"


class SourceNotReady(RuntimeError):
    """An official source has not published the requested session yet."""


class DailyAcceptanceError(RuntimeError):
    """A fully built candidate failed the existing real-data acceptance gates."""


class ProjectPublicationBusyError(RuntimeError):
    """Another process currently owns this project's publication transaction."""


@dataclass(frozen=True)
class ManifestSeries:
    series_id: str
    source: str
    source_symbol: str
    vintage_kind: str


@dataclass(frozen=True)
class SourceManifest:
    manifest_version: str
    availability_policy: str
    series: tuple[ManifestSeries, ...]

    @property
    def spot_series(self) -> tuple[ManifestSeries, ...]:
        return tuple(item for item in self.series if item.series_id != "VX_SETTLE")

    @property
    def vx_series(self) -> ManifestSeries:
        matches = [item for item in self.series if item.series_id == "VX_SETTLE"]
        if len(matches) != 1:
            raise ValueError("source manifest must define VX_SETTLE exactly once")
        return matches[0]


@dataclass(frozen=True)
class SourceAttempt:
    source: str
    source_symbol: str
    status: DownloadStatus
    url: str
    content_hash: str | None = None
    source_session: str | None = None
    path: str | None = None
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_symbol": self.source_symbol,
            "download_status": self.status.value,
            "url": self.url,
            "content_hash": self.content_hash,
            "source_session": self.source_session,
            "path": self.path,
            "message": self.message,
        }


@dataclass(frozen=True)
class SourceRefreshResult:
    attempts: tuple[SourceAttempt, ...] = ()
    observations_changed: bool = False
    vx_contracts_changed: bool = False


@dataclass(frozen=True)
class SourceFreshness:
    series_id: str
    source: str
    source_symbol: str
    status: FreshnessStatus
    expected_session: str
    latest_session: str | None
    observed_rows: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "series_id": self.series_id,
            "source": self.source,
            "source_symbol": self.source_symbol,
            "status": self.status.value,
            "expected_session": self.expected_session,
            "latest_session": self.latest_session,
            "observed_rows": self.observed_rows,
        }


@dataclass(frozen=True)
class FreshnessReport:
    target_session: str
    latest_complete_session: str | None
    sources: tuple[SourceFreshness, ...]

    @property
    def complete(self) -> bool:
        return bool(self.sources) and all(
            item.status == FreshnessStatus.FRESH for item in self.sources
        )


@dataclass(frozen=True)
class DailyCandidate:
    payload: dict[str, Any]
    metadata: dict[str, Any]
    features: pd.DataFrame
    states: pd.DataFrame
    targets: pd.DataFrame
    oof: pd.DataFrame
    probability_contract: dict[str, Any]
    cache_action: str
    acceptance_report: dict[str, Any]


@dataclass(frozen=True)
class DailyUpdateResult:
    status: DailyUpdateStatus
    updated_at: str
    target_session: str | None
    latest_complete_session: str | None
    last_good_session: str | None
    sources: dict[str, dict[str, Any]]
    message: str
    snapshot_path: str | None = None
    next_check_at: str | None = None
    catch_up_attempted: bool = False

    @property
    def successful(self) -> bool:
        return self.status in {DailyUpdateStatus.PUBLISHED, DailyUpdateStatus.ALREADY_CURRENT}

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "updated_at": self.updated_at,
            "target_session": self.target_session,
            "latest_complete_session": self.latest_complete_session,
            "last_good_session": self.last_good_session,
            "sources": self.sources,
            "data_sources": self.sources,
            "message": self.message,
            "snapshot_path": self.snapshot_path,
            "next_check_at": self.next_check_at,
            "catch_up_attempted": self.catch_up_attempted,
        }


RefreshHook = Callable[[ProjectPaths, pd.Timestamp, datetime], SourceRefreshResult]
CandidateBuilder = Callable[
    [ProjectPaths, pd.DataFrame, pd.DataFrame, pd.Timestamp], DailyCandidate
]
ReceiptWriter = Callable[[dict[str, Any], str | Path], Path]


def _validate_manifest_identities(manifest: SourceManifest) -> None:
    configured = {
        item.series_id: SourceIdentity(item.source, item.source_symbol, item.vintage_kind)
        for item in manifest.series
    }
    if configured == dict(OFFICIAL_SOURCE_IDENTITIES):
        return
    mismatches = {
        series_id: {
            "configured": configured.get(series_id),
            "required": OFFICIAL_SOURCE_IDENTITIES.get(series_id),
        }
        for series_id in sorted(set(configured) | set(OFFICIAL_SOURCE_IDENTITIES))
        if configured.get(series_id) != OFFICIAL_SOURCE_IDENTITIES.get(series_id)
    }
    raise ValueError(f"source manifest identity policy mismatch: {mismatches}")


def load_source_manifest(project_dir: str | Path) -> SourceManifest:
    path = Path(project_dir).resolve() / "configs" / "source_manifest.yaml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"source manifest must be a mapping: {path}")
    policy = str(loaded.get("availability_policy", ""))
    if policy != SOURCE_MANIFEST_POLICY:
        raise ValueError(f"unsupported source availability policy: {policy!r}")
    raw_series = loaded.get("series")
    if not isinstance(raw_series, dict):
        raise ValueError("source manifest series must be a mapping")
    series: list[ManifestSeries] = []
    for series_id, value in raw_series.items():
        if not isinstance(value, dict):
            raise ValueError(f"source manifest series {series_id} must be a mapping")
        series.append(
            ManifestSeries(
                series_id=str(series_id),
                source=str(value["source"]),
                source_symbol=str(value["source_symbol"]),
                vintage_kind=str(value["vintage_kind"]),
            )
        )
    manifest = SourceManifest(str(loaded.get("manifest_version", "")), policy, tuple(series))
    expected = {*REQUIRED_CORE_SERIES, "VX_SETTLE"}
    actual = {item.series_id for item in manifest.series}
    if actual != expected:
        raise ValueError(
            f"source manifest series mismatch: missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )
    _ = manifest.vx_series
    _validate_manifest_identities(manifest)
    return manifest


def _formal_history(frame: pd.DataFrame, entity_columns: list[str]) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    return select_historical_point_in_time(frame, entity_columns=entity_columns, formal_only=True)


def _latest_complete_vx_session(
    contracts: pd.DataFrame, *, not_after: pd.Timestamp
) -> pd.Timestamp | None:
    if contracts.empty or "session_date" not in contracts:
        return None
    sessions = pd.to_datetime(contracts["session_date"], errors="coerce").dropna().dt.normalize()
    sessions = (
        sessions.loc[sessions <= not_after.normalize()]
        .drop_duplicates()
        .sort_values(ascending=False)
    )
    for session in sessions:
        curve = select_standard_monthly_curve(contracts, session, count=7)
        if standard_monthly_curve_is_complete(curve):
            return pd.Timestamp(session).normalize()
    return None


def latest_common_complete_session(
    observations: pd.DataFrame,
    vx_contracts: pd.DataFrame,
    manifest: SourceManifest,
    *,
    not_after: pd.Timestamp | str | None = None,
) -> pd.Timestamp | None:
    _validate_manifest_identities(manifest)
    spot = _formal_history(admit_official_observations(observations), ["series_id"])
    vx = _formal_history(admit_official_vx_settlements(vx_contracts), ["contract_id"])
    if spot.empty or vx.empty or "value" not in spot:
        return None
    required = {item.series_id for item in manifest.spot_series}
    valid = spot.loc[spot["series_id"].isin(required) & spot["value"].notna()].copy()
    if valid.empty:
        return None
    valid["session_date"] = pd.to_datetime(valid["session_date"], errors="coerce").dt.normalize()
    counts = valid.groupby("session_date")["series_id"].nunique()
    candidates = counts.loc[counts.eq(len(required))].index
    if not_after is not None:
        cutoff = pd.Timestamp(not_after).normalize()
        candidates = candidates[candidates <= cutoff]
    candidates = pd.DatetimeIndex(candidates).sort_values(ascending=False)
    for candidate in candidates:
        if not is_session(candidate):
            continue
        curve = select_standard_monthly_curve(vx, candidate, count=7)
        if standard_monthly_curve_is_complete(curve):
            return pd.Timestamp(candidate).normalize()
    return None


def assess_source_freshness(
    observations: pd.DataFrame,
    vx_contracts: pd.DataFrame,
    manifest: SourceManifest,
    target_session: pd.Timestamp | str,
) -> FreshnessReport:
    _validate_manifest_identities(manifest)
    target = pd.Timestamp(target_session).normalize()
    expected = target.date().isoformat()
    spot = _formal_history(admit_official_observations(observations), ["series_id"])
    vx = _formal_history(admit_official_vx_settlements(vx_contracts), ["contract_id"])
    if not spot.empty:
        spot = spot.copy()
        spot["session_date"] = pd.to_datetime(spot["session_date"], errors="coerce").dt.normalize()
    sources: list[SourceFreshness] = []
    for spec in manifest.spot_series:
        rows = (
            spot.loc[spot["series_id"].eq(spec.series_id)]
            if not spot.empty and "series_id" in spot
            else pd.DataFrame()
        )
        rows = rows.loc[rows["value"].notna()] if not rows.empty and "value" in rows else rows
        latest = pd.Timestamp(rows["session_date"].max()).normalize() if not rows.empty else None
        target_rows = rows.loc[rows["session_date"].eq(target)] if not rows.empty else rows
        if not target_rows.empty:
            status = FreshnessStatus.FRESH
        elif latest is None:
            status = FreshnessStatus.MISSING
        elif latest < target:
            status = FreshnessStatus.STALE
        else:
            status = FreshnessStatus.SESSION_GAP
        sources.append(
            SourceFreshness(
                series_id=spec.series_id,
                source=spec.source,
                source_symbol=spec.source_symbol,
                status=status,
                expected_session=expected,
                latest_session=latest.date().isoformat() if latest is not None else None,
                observed_rows=len(target_rows),
            )
        )

    vx_spec = manifest.vx_series
    curve = select_standard_monthly_curve(vx, target, count=7) if not vx.empty else pd.DataFrame()
    latest_vx = _latest_complete_vx_session(vx, not_after=target)
    if standard_monthly_curve_is_complete(curve):
        vx_status = FreshnessStatus.FRESH
    elif vx.empty:
        vx_status = FreshnessStatus.MISSING
    elif not curve.empty:
        vx_status = FreshnessStatus.INCOMPLETE
    elif latest_vx is not None and latest_vx < target:
        vx_status = FreshnessStatus.STALE
    else:
        vx_status = FreshnessStatus.SESSION_GAP
    sources.append(
        SourceFreshness(
            series_id=vx_spec.series_id,
            source=vx_spec.source,
            source_symbol=vx_spec.source_symbol,
            status=vx_status,
            expected_session=expected,
            latest_session=latest_vx.date().isoformat() if latest_vx is not None else None,
            observed_rows=len(curve),
        )
    )
    latest = latest_common_complete_session(observations, vx_contracts, manifest, not_after=target)
    return FreshnessReport(
        target_session=expected,
        latest_complete_session=latest.date().isoformat() if latest is not None else None,
        sources=tuple(sources),
    )


def canonical_vx_contract_id(year: int, month: int) -> str:
    try:
        return f"{VX_MONTH_CODES[month]} ({VX_MONTH_NAMES[month]} {year:04d})"
    except KeyError as exc:
        raise ValueError(f"invalid VX contract month: {month}") from exc


def parse_cfe_daily_settlement_csv(
    content: bytes,
    session_date: pd.Timestamp | str,
    *,
    ingested_at: datetime | None = None,
) -> pd.DataFrame:
    frame = pd.read_csv(io.BytesIO(content))
    frame.columns = [str(column).strip() for column in frame.columns]
    required = {"Product", "Symbol", "Expiration Date", "Price"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"CFE daily settlement columns missing: {sorted(missing)}")
    frame = frame.loc[frame["Product"].astype(str).str.strip().eq("VX")].copy()
    frame["expiration_date"] = pd.to_datetime(
        frame["Expiration Date"], errors="coerce"
    ).dt.normalize()
    frame["source_contract_symbol"] = frame["Symbol"].astype(str).str.strip()
    frame = frame.loc[
        frame["source_contract_symbol"].str.fullmatch(r"VX/[FGHJKMNQUVXZ]\d{1,2}", na=False)
        & frame["expiration_date"].notna()
    ]
    frame = frame.loc[
        frame["expiration_date"].map(
            lambda value: pd.Timestamp(value).date()
            == vix_final_settlement_date(pd.Timestamp(value).year, pd.Timestamp(value).month)
        )
    ]
    if frame.empty:
        raise SourceNotReady("CFE daily settlement has no published standard-monthly VX rows")
    symbol_parts = frame["source_contract_symbol"].str.extract(r"^VX/([FGHJKMNQUVXZ])(\d{1,2})$")
    expected_codes = frame["expiration_date"].map(
        lambda value: VX_MONTH_CODES[pd.Timestamp(value).month]
    )
    expected_years = frame["expiration_date"].map(
        lambda value: {
            str(pd.Timestamp(value).year % 10),
            f"{pd.Timestamp(value).year % 100:02d}",
        }
    )
    symbol_matches_expiration = symbol_parts[0].eq(expected_codes) & pd.Series(
        [token in allowed for token, allowed in zip(symbol_parts[1], expected_years, strict=True)],
        index=frame.index,
    )
    if not bool(symbol_matches_expiration.all()):
        mismatches = frame.loc[
            ~symbol_matches_expiration, ["source_contract_symbol", "expiration_date"]
        ].to_dict("records")
        raise ValueError(f"CFE VX symbol/expiration mismatch: {mismatches}")
    cleaned_price = (
        frame["Price"]
        .astype(str)
        .str.replace("*", "", regex=False)
        .str.replace(",", "", regex=False)
    )
    frame["settle"] = pd.to_numeric(cleaned_price, errors="coerce")
    if frame["settle"].isna().any() or frame["settle"].le(0).any():
        raise ValueError("CFE daily settlement has an invalid standard-monthly VX price")
    frame["contract_id"] = frame["expiration_date"].map(
        lambda value: canonical_vx_contract_id(pd.Timestamp(value).year, pd.Timestamp(value).month)
    )
    frame = frame.sort_values(["expiration_date", "contract_id"]).drop_duplicates(
        "expiration_date", keep="last"
    )

    session = pd.Timestamp(session_date).normalize()
    ingested = ingested_at or datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    for record in frame.itertuples(index=False):
        expiration = pd.Timestamp(record.expiration_date)
        contract_id = str(record.contract_id)
        settle = float(record.settle)
        final_timestamp = final_settlement_timestamp(expiration.year, expiration.month).isoformat()
        semantic = {
            "series_id": "VX_SETTLE",
            "session_date": session,
            "contract_id": contract_id,
            "settle": settle,
            "final_settlement_timestamp": final_timestamp,
            "unit": "vix_points",
            "source": "CFE",
            "source_symbol": "VX_STANDARD_MONTHLY",
            "methodology_version": "CFE_VX_MONTHLY_OFFICIAL_SETTLEMENT_V1",
            "vintage_kind": "ASSUMED_PIT",
        }
        rows.append(
            {
                "session_date": session,
                "contract_id": contract_id,
                "contract_year": expiration.year,
                "contract_month": expiration.month,
                "final_settlement_date": expiration,
                "final_settlement_timestamp": final_timestamp,
                "settle": settle,
                "unit": "vix_points",
                "source": "CFE",
                "source_symbol": "VX_STANDARD_MONTHLY",
                "series_id": "VX_SETTLE",
                "value": settle,
                "observed_at": observed_at_eod(session).isoformat(),
                "available_at": decision_as_of(session).isoformat(),
                "ingested_at": ingested.astimezone(UTC).isoformat(),
                "methodology_version": "CFE_VX_MONTHLY_OFFICIAL_SETTLEMENT_V1",
                "vintage_kind": "ASSUMED_PIT",
                "is_standard_monthly": True,
                "revision_id": content_revision_id(**semantic),
            }
        )
    return pd.DataFrame(rows).sort_values("final_settlement_date").reset_index(drop=True)


def import_cboe_spx_history_bytes(
    content: bytes,
    *,
    start_session: pd.Timestamp | str,
    end_session: pd.Timestamp | str,
    ingested_at: datetime | None = None,
) -> pd.DataFrame:
    frame = pd.read_csv(io.BytesIO(content))
    frame.columns = [str(column).strip().upper() for column in frame.columns]
    if not {"DATE", "SPX"}.issubset(frame.columns):
        raise ValueError("Cboe SPX history requires DATE,SPX")
    frame["DATE"] = pd.to_datetime(frame["DATE"], errors="coerce").dt.normalize()
    frame["SPX"] = pd.to_numeric(frame["SPX"], errors="coerce")
    start, end = pd.Timestamp(start_session).normalize(), pd.Timestamp(end_session).normalize()
    official_sessions = sessions_in_range(start.date(), end.date())
    frame = frame.loc[
        frame["DATE"].isin(official_sessions) & frame["SPX"].notna() & frame["SPX"].gt(0),
        ["DATE", "SPX"],
    ]
    if frame.empty:
        raise ValueError(f"Cboe SPX history has no usable rows in {start.date()}..{end.date()}")
    with tempfile.TemporaryDirectory(prefix="matvix-spx-") as directory:
        filtered = Path(directory) / "SPX_History.csv"
        frame.to_csv(filtered, index=False)
        return import_spx_close(
            filtered,
            source="CBOE",
            source_symbol="SPX",
            ingested_at=ingested_at,
        )


def _content_hash(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _atomic_store_bytes(content: bytes, target: Path) -> tuple[bool, str]:
    digest = _content_hash(content)
    if target.exists() and _content_hash(target.read_bytes()) == digest:
        return False, digest
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(content)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return True, digest


def _download_bytes(url: str, *, timeout: int) -> bytes:
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "MatVIX/1.1"})
    if response.status_code == 404:
        raise SourceNotReady(f"official source has not published this session: {url}")
    response.raise_for_status()
    return bytes(response.content)


def _download_cfe_settlement_bytes(
    url: str, *, target_session: pd.Timestamp, timeout: int
) -> bytes:
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "MatVIX/1.1"})
    if response.status_code == 404:
        raise SourceNotReady(f"official source has not published this session: {url}")
    response.raise_for_status()
    disposition = str(response.headers.get("Content-Disposition", ""))
    match = re.search(r"FuturesSettlements_(\d{4}-\d{2}-\d{2})\.csv", disposition)
    if match is None:
        raise ValueError("CFE settlement response is missing its dated filename")
    published_session = match.group(1)
    expected_session = target_session.date().isoformat()
    if published_session != expected_session:
        raise SourceNotReady(
            f"CFE settlement fallback is {published_session}; waiting for {expected_session}"
        )
    return bytes(response.content)


def _latest_frame_session(frame: pd.DataFrame) -> str | None:
    if frame.empty or "session_date" not in frame:
        return None
    latest = pd.to_datetime(frame["session_date"], errors="coerce").max()
    return pd.Timestamp(latest).date().isoformat() if pd.notna(latest) else None


def _spx_start_session(
    observations: pd.DataFrame, vx_contracts: pd.DataFrame, target: pd.Timestamp
) -> pd.Timestamp:
    if not observations.empty and {"series_id", "session_date"}.issubset(observations.columns):
        spx = observations.loc[observations["series_id"].eq("SPX_CLOSE"), "session_date"]
        if not spx.empty:
            return pd.to_datetime(spx).min().normalize()
    if not vx_contracts.empty and "session_date" in vx_contracts:
        return pd.to_datetime(vx_contracts["session_date"]).min().normalize()
    return target.normalize()


def _merge_and_write(
    existing: pd.DataFrame,
    incoming: pd.DataFrame,
    *,
    entity_columns: list[str],
    path: Path,
) -> bool:
    if incoming.empty:
        return False
    incoming = incoming.drop_duplicates("revision_id", keep="last").reset_index(drop=True)
    merged = (
        merge_revision_history(existing, incoming, entity_columns=entity_columns)
        if not existing.empty
        else incoming
    )
    changed = len(merged) != len(existing)
    if changed:
        write_parquet(merged, path)
    return changed


def _release_generation_timestamp(value: object, *, relative_path: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"release generation ingested_at is missing: {relative_path}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"release generation ingested_at is invalid: {relative_path}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"release generation ingested_at must be timezone-aware: {relative_path}")
    return parsed.astimezone(UTC)


def import_release_source_generation(
    paths: ProjectPaths,
    *,
    live_root: str | Path,
    manifest_path: str | Path,
) -> dict[str, str | int]:
    """Import one checksummed, offline live-source generation over the vendor baseline."""

    if not paths.observations.exists() or not paths.vx_contracts.exists():
        raise ValueError("release generation requires an imported vendor baseline")
    source_manifest_path = Path(manifest_path)
    release_manifest = read_json(paths.root / "MATVIX_V3_RELEASE_MANIFEST.json")
    authorized_data = release_manifest.get("authorized_data_requirement")
    if not isinstance(authorized_data, dict):
        raise ValueError("release authorized-data requirement is missing")
    expected_manifest_sha256 = authorized_data.get("live_generation_manifest_sha256")
    expected_manifest_entries = authorized_data.get("live_generation_manifest_entries")
    if not isinstance(expected_manifest_sha256, str) or not isinstance(
        expected_manifest_entries, int
    ):
        raise ValueError("release live-generation identity is missing")
    try:
        actual_manifest_sha256 = hashlib.sha256(source_manifest_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError("release source generation manifest is unavailable") from exc
    if actual_manifest_sha256 != expected_manifest_sha256:
        raise ValueError("release source generation manifest SHA-256 mismatch")
    manifest = read_json(source_manifest_path)
    if manifest.get("manifest_version") != "1.0.0":
        raise ValueError("unsupported release source generation manifest")
    generation_id = manifest.get("generation_id")
    latest_session = manifest.get("latest_session")
    raw_files = manifest.get("files")
    if not isinstance(generation_id, str) or not generation_id:
        raise ValueError("release source generation_id is missing")
    if not isinstance(latest_session, str):
        raise ValueError("release source latest_session is missing")
    try:
        parsed_latest = datetime.strptime(latest_session, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise ValueError("release source latest_session must be YYYY-MM-DD") from exc
    if parsed_latest != latest_session:
        raise ValueError("release source latest_session must be canonical YYYY-MM-DD")
    if not isinstance(raw_files, dict) or not raw_files:
        raise ValueError("release source generation files are missing")
    if len(raw_files) != expected_manifest_entries:
        raise ValueError("release source generation manifest entry count mismatch")

    observations = read_parquet(paths.observations)
    vx_contracts = read_parquet(paths.vx_contracts)
    observation_frames: list[pd.DataFrame] = []
    vx_frames: list[pd.DataFrame] = []
    seen_symbols: set[str] = set()
    seen_spx = False
    cfe_sessions: set[str] = set()
    root = Path(live_root).resolve()
    files = cast(dict[str, Any], raw_files)

    for relative_name, raw_spec in sorted(files.items()):
        if not isinstance(raw_spec, dict):
            raise ValueError(f"release source file spec must be an object: {relative_name}")
        relative = Path(relative_name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"release source path is unsafe: {relative_name}")
        source_path = root / relative
        try:
            content = source_path.read_bytes()
        except OSError as exc:
            raise ValueError(f"release source file is unavailable: {relative_name}") from exc
        expected_sha256 = raw_spec.get("sha256")
        if not isinstance(expected_sha256, str) or re.fullmatch(
            r"[0-9a-f]{64}", expected_sha256
        ) is None:
            raise ValueError(f"release source sha256 is invalid: {relative_name}")
        actual_sha256 = hashlib.sha256(content).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError(f"release source sha256 mismatch: {relative_name}")
        ingested_at = _release_generation_timestamp(
            raw_spec.get("ingested_at"), relative_path=relative_name
        )
        kind = raw_spec.get("kind")

        if kind == "CBOE_INDEX_HISTORY":
            symbol = raw_spec.get("symbol")
            if not isinstance(symbol, str) or symbol not in SUPPORTED_SYMBOLS:
                raise ValueError(f"release Cboe symbol is invalid: {relative_name}")
            if relative.as_posix() != f"cboe/{symbol}_History.csv" or symbol in seen_symbols:
                raise ValueError(f"release Cboe identity is invalid: {relative_name}")
            observation_frames.append(
                import_cboe_history(source_path, symbol, ingested_at=ingested_at)
            )
            seen_symbols.add(symbol)
        elif kind == "CBOE_SPX_HISTORY":
            if relative.as_posix() != "cboe/SPX_History.csv" or seen_spx:
                raise ValueError(f"release SPX identity is invalid: {relative_name}")
            start_session = _spx_start_session(
                observations, vx_contracts, pd.Timestamp(latest_session)
            )
            observation_frames.append(
                import_cboe_spx_history_bytes(
                    content,
                    start_session=start_session,
                    end_session=latest_session,
                    ingested_at=ingested_at,
                )
            )
            seen_spx = True
        elif kind == "CFE_DAILY_SETTLEMENT":
            session = raw_spec.get("session_date")
            if not isinstance(session, str):
                raise ValueError(f"release CFE session is missing: {relative_name}")
            if relative.as_posix() != f"cfe/settlement_{session}.csv" or session in cfe_sessions:
                raise ValueError(f"release CFE identity is invalid: {relative_name}")
            vx_frames.append(
                parse_cfe_daily_settlement_csv(content, session, ingested_at=ingested_at)
            )
            cfe_sessions.add(session)
        else:
            raise ValueError(f"release source kind is invalid: {relative_name}")

    if seen_symbols != set(SUPPORTED_SYMBOLS) or not seen_spx:
        raise ValueError("release source generation does not cover the full Cboe Core")
    if latest_session not in cfe_sessions:
        raise ValueError("release source generation lacks latest-session CFE settlement")

    incoming_observations = pd.concat(observation_frames, ignore_index=True)
    incoming_vx = pd.concat(vx_frames, ignore_index=True)
    merged_observations = merge_revision_history(
        observations,
        incoming_observations,
        entity_columns=["series_id"],
    )
    merged_vx = merge_revision_history(
        vx_contracts,
        incoming_vx,
        entity_columns=["contract_id"],
    )
    if len(merged_observations) != len(observations):
        write_parquet(merged_observations, paths.observations)
    if len(merged_vx) != len(vx_contracts):
        write_parquet(merged_vx, paths.vx_contracts)
    return {
        "generation_id": generation_id,
        "latest_session": latest_session,
        "verified_files": len(files),
        "observations": len(merged_observations),
        "vx_rows": len(merged_vx),
        "added_observations": len(merged_observations) - len(observations),
        "added_vx_rows": len(merged_vx) - len(vx_contracts),
    }


def refresh_official_sources(
    paths: ProjectPaths,
    target_session: pd.Timestamp,
    now: datetime,
    *,
    live_root: str | Path | None = None,
    timeout: int = 60,
) -> SourceRefreshResult:
    """Refresh official live files without touching the checksummed accepted baseline."""

    target = pd.Timestamp(target_session).normalize()
    root = Path(live_root) if live_root is not None else paths.root / "data" / "raw" / "live"
    observations = (
        read_parquet(paths.observations) if paths.observations.exists() else pd.DataFrame()
    )
    vx_contracts = (
        read_parquet(paths.vx_contracts) if paths.vx_contracts.exists() else pd.DataFrame()
    )
    observation_frames: list[pd.DataFrame] = []
    vx_frames: list[pd.DataFrame] = []
    attempts: list[SourceAttempt] = []

    with tempfile.TemporaryDirectory(prefix="matvix-cboe-") as directory:
        temporary_root = Path(directory)
        for symbol in SUPPORTED_SYMBOLS:
            url = CBOE_HISTORY_URL.format(symbol=symbol)
            live_path = root / "cboe" / f"{symbol}_History.csv"
            try:
                temporary = download_cboe_history(symbol, temporary_root, timeout=timeout)
                content = temporary.read_bytes()
                parsed = import_cboe_history(temporary, symbol, ingested_at=now.astimezone(UTC))
                changed, digest = _atomic_store_bytes(content, live_path)
                observation_frames.append(parsed)
                attempts.append(
                    SourceAttempt(
                        "CBOE",
                        symbol,
                        DownloadStatus.UPDATED if changed else DownloadStatus.UNCHANGED,
                        url,
                        digest,
                        _latest_frame_session(parsed),
                        str(live_path),
                    )
                )
            except (OSError, ValueError, requests.RequestException) as exc:
                if live_path.exists():
                    parsed = import_cboe_history(live_path, symbol, ingested_at=now.astimezone(UTC))
                    observation_frames.append(parsed)
                    attempts.append(
                        SourceAttempt(
                            "CBOE",
                            symbol,
                            DownloadStatus.REUSED_LAST_SUCCESS,
                            url,
                            _content_hash(live_path.read_bytes()),
                            _latest_frame_session(parsed),
                            str(live_path),
                            str(exc),
                        )
                    )
                else:
                    attempts.append(
                        SourceAttempt("CBOE", symbol, DownloadStatus.FAILED, url, message=str(exc))
                    )

    spx_path = root / "cboe" / "SPX_History.csv"
    spx_start = _spx_start_session(observations, vx_contracts, target)
    try:
        spx_content = _download_bytes(CBOE_SPX_HISTORY_URL, timeout=timeout)
        spx_frame = import_cboe_spx_history_bytes(
            spx_content,
            start_session=spx_start,
            end_session=target,
            ingested_at=now.astimezone(UTC),
        )
        changed, digest = _atomic_store_bytes(spx_content, spx_path)
        observation_frames.append(spx_frame)
        attempts.append(
            SourceAttempt(
                "CBOE",
                "SPX",
                DownloadStatus.UPDATED if changed else DownloadStatus.UNCHANGED,
                CBOE_SPX_HISTORY_URL,
                digest,
                _latest_frame_session(spx_frame),
                str(spx_path),
            )
        )
    except (OSError, ValueError, requests.RequestException) as exc:
        if spx_path.exists():
            spx_frame = import_cboe_spx_history_bytes(
                spx_path.read_bytes(),
                start_session=spx_start,
                end_session=target,
                ingested_at=now.astimezone(UTC),
            )
            observation_frames.append(spx_frame)
            attempts.append(
                SourceAttempt(
                    "CBOE",
                    "SPX",
                    DownloadStatus.REUSED_LAST_SUCCESS,
                    CBOE_SPX_HISTORY_URL,
                    _content_hash(spx_path.read_bytes()),
                    _latest_frame_session(spx_frame),
                    str(spx_path),
                    str(exc),
                )
            )
        else:
            attempts.append(
                SourceAttempt(
                    "CBOE", "SPX", DownloadStatus.FAILED, CBOE_SPX_HISTORY_URL, message=str(exc)
                )
            )

    cfe_url = CFE_DAILY_SETTLEMENT_URL.format(session=target.date().isoformat())
    cfe_path = root / "cfe" / f"settlement_{target.date().isoformat()}.csv"
    try:
        cfe_content = _download_cfe_settlement_bytes(
            cfe_url, target_session=target, timeout=timeout
        )
        cfe_frame = parse_cfe_daily_settlement_csv(
            cfe_content, target, ingested_at=now.astimezone(UTC)
        )
        changed, digest = _atomic_store_bytes(cfe_content, cfe_path)
        vx_frames.append(cfe_frame)
        attempts.append(
            SourceAttempt(
                "CFE",
                "VX_STANDARD_MONTHLY",
                DownloadStatus.UPDATED if changed else DownloadStatus.UNCHANGED,
                cfe_url,
                digest,
                target.date().isoformat(),
                str(cfe_path),
            )
        )
    except SourceNotReady as exc:
        attempts.append(
            SourceAttempt(
                "CFE", "VX_STANDARD_MONTHLY", DownloadStatus.NOT_READY, cfe_url, message=str(exc)
            )
        )
    except (OSError, ValueError, requests.RequestException) as exc:
        if cfe_path.exists():
            cfe_frame = parse_cfe_daily_settlement_csv(
                cfe_path.read_bytes(), target, ingested_at=now.astimezone(UTC)
            )
            vx_frames.append(cfe_frame)
            attempts.append(
                SourceAttempt(
                    "CFE",
                    "VX_STANDARD_MONTHLY",
                    DownloadStatus.REUSED_LAST_SUCCESS,
                    cfe_url,
                    _content_hash(cfe_path.read_bytes()),
                    target.date().isoformat(),
                    str(cfe_path),
                    str(exc),
                )
            )
        else:
            attempts.append(
                SourceAttempt(
                    "CFE",
                    "VX_STANDARD_MONTHLY",
                    DownloadStatus.FAILED,
                    cfe_url,
                    message=str(exc),
                )
            )

    incoming_observations = (
        pd.concat(observation_frames, ignore_index=True) if observation_frames else pd.DataFrame()
    )
    incoming_vx = pd.concat(vx_frames, ignore_index=True) if vx_frames else pd.DataFrame()
    observations_changed = _merge_and_write(
        observations,
        incoming_observations,
        entity_columns=["series_id"],
        path=paths.observations,
    )
    vx_changed = _merge_and_write(
        vx_contracts,
        incoming_vx,
        entity_columns=["contract_id"],
        path=paths.vx_contracts,
    )
    return SourceRefreshResult(tuple(attempts), observations_changed, vx_changed)


def build_daily_candidate(
    paths: ProjectPaths,
    observations: pd.DataFrame,
    vx_contracts: pd.DataFrame,
    target_session: pd.Timestamp,
) -> DailyCandidate:
    features, states = build_state_history(observations, vx_contracts)
    matching = states.loc[
        pd.to_datetime(states["session_date"]).dt.normalize().eq(target_session.normalize())
    ]
    if matching.empty or str(matching.iloc[-1].get("data_status")) != DataStatus.OK.value:
        raise DailyAcceptanceError(f"target state is not data_status=OK: {target_session.date()}")
    targets, oof, contract, cache_action = resolve_persisted_probability_artifacts(
        paths,
        states,
        formal_runtime_required=True,
        persist=False,
    )
    payload, metadata, _, _ = build_snapshot_payload(
        states,
        observations,
        vx_contracts,
        session_date=target_session,
        formal_runtime_required=True,
        target_ledger=targets,
        oof_ledger=oof,
    )
    metadata["artifact_cache"] = {
        "action": cache_action,
        "state_history": contract["state_history"],
    }
    acceptance = build_real_acceptance_report(
        observations=observations,
        vx_contracts=vx_contracts,
        states=states,
        targets=targets,
        oof=oof,
        snapshot=payload,
    )
    if not bool(acceptance.get("passed")):
        failures = ",".join(failed_gate_names(acceptance))
        raise DailyAcceptanceError(f"real-data acceptance failed: {failures}")
    return DailyCandidate(
        payload,
        metadata,
        features,
        states,
        targets,
        oof,
        contract,
        cache_action,
        acceptance,
    )


def _canonical_value(value: object) -> object:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (pd.Timestamp, np.datetime64, datetime)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
        return None if np.isnan(value) else str(value)
    return value


def _frame_digest(frame: pd.DataFrame) -> str:
    columns = sorted(str(column) for column in frame.columns)
    canonical = frame.reindex(columns=columns).reset_index(drop=True)
    digest = hashlib.sha256()
    digest.update(json.dumps(columns, separators=(",", ":")).encode("utf-8"))
    for row in canonical.itertuples(index=False, name=None):
        digest.update(
            json.dumps(
                [_canonical_value(value) for value in row],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    return digest.hexdigest()


def frame_content_digest(frame: pd.DataFrame) -> str:
    """Stable identity for one exact dashboard-supporting DataFrame generation."""

    return "sha256:" + _frame_digest(frame)


def _write_parquet_if_changed(frame: pd.DataFrame, path: Path) -> bool:
    if path.exists() and _frame_digest(read_parquet(path)) == _frame_digest(frame):
        return False
    write_parquet(frame, path)
    return True


def runtime_status_path(project_dir: str | Path) -> Path:
    return Path(project_dir).resolve() / RUNTIME_STATUS_RELATIVE_PATH


def read_update_status(project_dir: str | Path) -> dict[str, Any] | None:
    path = runtime_status_path(project_dir)
    return read_json(path) if path.exists() else None


def write_update_status(project_dir: str | Path, result: DailyUpdateResult) -> Path:
    return write_json(result.as_dict(), runtime_status_path(project_dir))


def acceptance_receipt_path(paths: ProjectPaths, session: pd.Timestamp | str) -> Path:
    selected = pd.Timestamp(session).date().isoformat()
    return paths.root / "artifacts" / "acceptance" / f"real_acceptance_{selected}.json"


def _stable_snapshot_publication(
    snapshot_path: str | Path,
    *,
    expected_session: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = Path(snapshot_path)
    for _ in range(2):
        try:
            before = path.stat()
            content = path.read_bytes()
            after = path.stat()
        except OSError as exc:
            raise DailyAcceptanceError(f"snapshot publication binding unreadable: {path}") from exc
        before_token = (before.st_ino, before.st_mtime_ns, before.st_size)
        after_token = (after.st_ino, after.st_mtime_ns, after.st_size)
        if before_token != after_token or len(content) != after.st_size:
            continue
        try:
            payload = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DailyAcceptanceError(
                f"snapshot publication binding invalid JSON: {path}"
            ) from exc
        if not isinstance(payload, dict):
            raise DailyAcceptanceError(f"snapshot publication binding is not an object: {path}")
        session = payload.get("session_date")
        if not isinstance(session, str):
            raise DailyAcceptanceError("snapshot publication binding has no session_date")
        try:
            normalized_session = pd.Timestamp(session).date().isoformat()
        except (TypeError, ValueError) as exc:
            raise DailyAcceptanceError(
                "snapshot publication binding has invalid session_date"
            ) from exc
        if normalized_session != session or (
            expected_session is not None and session != expected_session
        ):
            raise DailyAcceptanceError(
                "snapshot publication binding session does not match receipt"
            )
        binding = {
            "binding_version": PUBLICATION_BINDING_VERSION,
            "session_date": session,
            "snapshot_sha256": _content_hash(content),
            "snapshot_size": len(content),
        }
        return payload, binding
    raise DailyAcceptanceError(f"snapshot changed while publication binding was read: {path}")


def snapshot_publication_binding(
    snapshot_path: str | Path,
    *,
    expected_session: str | None = None,
) -> dict[str, Any]:
    """Return the exact on-disk snapshot identity a passing receipt must authorize."""

    _, binding = _stable_snapshot_publication(
        snapshot_path,
        expected_session=expected_session,
    )
    return binding


def with_snapshot_publication_binding(
    report: Mapping[str, Any], snapshot_path: str | Path
) -> dict[str, Any]:
    """Copy an acceptance report and bind it to one exact daily snapshot."""

    session = report.get("session_date")
    if not isinstance(session, str):
        raise DailyAcceptanceError("acceptance receipt session is missing")
    bound = dict(report)
    bound["publication_binding"] = snapshot_publication_binding(
        snapshot_path,
        expected_session=session,
    )
    return bound


def _accepted_snapshot_session(paths: ProjectPaths, receipt_path: Path) -> str | None:
    try:
        receipt = read_json(receipt_path)
        session = str(receipt["session_date"])
        normalized = pd.Timestamp(session).date().isoformat()
        if normalized != session or receipt_path.name != f"real_acceptance_{session}.json":
            return None
        if receipt.get("passed") is not True:
            return None
        snapshot_path = paths.daily_output_dir / f"{session}.json"
        snapshot, expected_binding = _stable_snapshot_publication(
            snapshot_path,
            expected_session=session,
        )
        if snapshot.get("session_date") != session:
            return None
        if snapshot.get("data_status") != DataStatus.OK.value:
            return None
        publication_binding = receipt.get("publication_binding")
        if not isinstance(publication_binding, Mapping):
            return None
        if dict(publication_binding) != expected_binding:
            return None
        if receipt_path.stat().st_mtime_ns < snapshot_path.stat().st_mtime_ns:
            return None
    except (DailyAcceptanceError, KeyError, OSError, TypeError, ValueError):
        return None
    return session


def last_good_session(paths: ProjectPaths) -> str | None:
    receipt_dir = paths.root / "artifacts" / "acceptance"
    candidates = [
        session
        for path in receipt_dir.glob("real_acceptance_*.json")
        if (session := _accepted_snapshot_session(paths, path)) is not None
    ]
    return max(candidates) if candidates else None


def _release_receipt(
    paths: ProjectPaths,
    target: pd.Timestamp,
    candidate: DailyCandidate,
) -> dict[str, Any]:
    report = dict(candidate.acceptance_report)
    session = target.date().isoformat()
    if report.get("passed") is not True:
        raise DailyAcceptanceError("acceptance receipt is not passing")
    if report.get("session_date") != session:
        raise DailyAcceptanceError("acceptance receipt session does not match target")
    state_history = candidate.probability_contract.get("state_history")
    state_digest = (
        state_history.get("relevant_columns_digest") if isinstance(state_history, Mapping) else None
    )
    if not isinstance(state_digest, str) or not state_digest.startswith("sha256:"):
        raise DailyAcceptanceError("probability artifact state digest is missing")
    report["release_contract"] = {
        **asdict(validate_frozen_config(paths.root)),
        "probability_artifact_cache": candidate.cache_action,
        "probability_artifact_state_digest": state_digest,
        "dashboard_state_history_digest": frame_content_digest(candidate.states),
        "dashboard_oof_digest": frame_content_digest(candidate.oof),
    }
    return report


def _receipt_is_current(
    path: Path,
    snapshot_path: Path,
    expected: dict[str, Any],
) -> bool:
    try:
        return (
            read_json(path) == expected
            and path.stat().st_mtime_ns >= snapshot_path.stat().st_mtime_ns
        )
    except (OSError, TypeError, ValueError):
        return False


def _acquire_daily_update_lock(
    paths: ProjectPaths,
    *,
    current: datetime,
    target: pd.Timestamp,
) -> TextIO | None:
    lock_path = paths.root / DAILY_UPDATE_LOCK_RELATIVE_PATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        return None
    try:
        lock_file.seek(0)
        lock_file.truncate()
        json.dump(
            {
                "pid": os.getpid(),
                "started_at": current.astimezone(UTC).isoformat(),
                "target_session": target.date().isoformat(),
            },
            lock_file,
            ensure_ascii=False,
            sort_keys=True,
        )
        lock_file.write("\n")
        lock_file.flush()
        os.fsync(lock_file.fileno())
    except Exception:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()
        raise
    return lock_file


def _release_daily_update_lock(lock_file: TextIO) -> None:
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        lock_file.close()


@contextmanager
def project_publication_lock(
    project_dir: str | Path,
    target_session: pd.Timestamp | str,
    *,
    current: datetime | None = None,
) -> Iterator[None]:
    """Hold the one nonblocking lock shared by automatic and manual publication."""

    acquired_at = current or datetime.now(UTC)
    if acquired_at.tzinfo is None:
        raise ValueError("current must be timezone-aware")
    target = pd.Timestamp(target_session).normalize()
    paths = ProjectPaths(Path(project_dir).resolve())
    lock_file = _acquire_daily_update_lock(paths, current=acquired_at, target=target)
    if lock_file is None:
        raise ProjectPublicationBusyError(
            f"another MatVIX publication holds the project lock for {paths.root}"
        )
    try:
        yield
    finally:
        _release_daily_update_lock(lock_file)


def _source_status_payload(
    report: FreshnessReport, refresh: SourceRefreshResult
) -> dict[str, dict[str, Any]]:
    attempts = {(item.source, item.source_symbol): item for item in refresh.attempts}
    result: dict[str, dict[str, Any]] = {}
    for source in report.sources:
        value = source.as_dict()
        attempt = attempts.get((source.source, source.source_symbol))
        if attempt is not None:
            value.update(attempt.as_dict())
            value["status"] = source.status.value
        result[source.series_id] = value
    return result


def _result(
    *,
    status: DailyUpdateStatus,
    now: datetime,
    target: pd.Timestamp,
    report: FreshnessReport,
    refresh: SourceRefreshResult,
    last_good: str | None,
    message: str,
    snapshot_path: Path | None = None,
    next_check_at: datetime | None = None,
) -> DailyUpdateResult:
    return DailyUpdateResult(
        status=status,
        updated_at=now.astimezone(UTC).isoformat(),
        target_session=target.date().isoformat(),
        latest_complete_session=report.latest_complete_session,
        last_good_session=last_good,
        sources=_source_status_payload(report, refresh),
        message=message,
        snapshot_path=str(snapshot_path) if snapshot_path is not None else None,
        next_check_at=next_check_at.astimezone(UTC).isoformat() if next_check_at else None,
    )


def _run_daily_update_locked(
    project_dir: str | Path,
    target_session: pd.Timestamp | str,
    *,
    now: datetime | None = None,
    refresh: RefreshHook | None = None,
    manifest: SourceManifest | None = None,
    candidate_builder: CandidateBuilder = build_daily_candidate,
    receipt_writer: ReceiptWriter = write_real_acceptance_report,
) -> DailyUpdateResult:
    """Build and publish one accepted session while the project lock is held."""

    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    target = pd.Timestamp(target_session).normalize()
    if not is_session(target):
        raise ValueError(f"target is not an XNYS session: {target.date()}")
    paths = ProjectPaths(Path(project_dir).resolve())
    source_manifest = manifest or load_source_manifest(paths.root)
    previous_last_good = last_good_session(paths)
    refresh_result = SourceRefreshResult()
    refresh_error: str | None = None
    if refresh is not None:
        try:
            refresh_result = refresh(paths, target, current)
        except Exception as exc:  # the persisted ledgers may still be complete and usable
            refresh_error = f"{type(exc).__name__}: {exc}"

    observations = (
        read_parquet(paths.observations) if paths.observations.exists() else pd.DataFrame()
    )
    vx_contracts = (
        read_parquet(paths.vx_contracts) if paths.vx_contracts.exists() else pd.DataFrame()
    )
    try:
        report = assess_source_freshness(observations, vx_contracts, source_manifest, target)
    except Exception as exc:
        empty_report = FreshnessReport(target.date().isoformat(), None, ())
        result = _result(
            status=DailyUpdateStatus.FAILED,
            now=current,
            target=target,
            report=empty_report,
            refresh=refresh_result,
            last_good=previous_last_good,
            message=f"source freshness evaluation failed: {type(exc).__name__}: {exc}",
        )
        write_update_status(paths.root, result)
        return result

    due_at = decision_as_of(target)
    if current.astimezone(NY) < due_at:
        result = _result(
            status=DailyUpdateStatus.NOT_DUE,
            now=current,
            target=target,
            report=report,
            refresh=refresh_result,
            last_good=previous_last_good,
            message=f"formal publication is gated until {due_at.isoformat()}",
            next_check_at=due_at,
        )
        write_update_status(paths.root, result)
        return result

    if not report.complete or report.latest_complete_session != target.date().isoformat():
        detail = f"; refresh_error={refresh_error}" if refresh_error else ""
        result = _result(
            status=DailyUpdateStatus.SOURCES_PENDING,
            now=current,
            target=target,
            report=report,
            refresh=refresh_result,
            last_good=previous_last_good,
            message=f"required sources are not complete for {target.date()}{detail}",
        )
        write_update_status(paths.root, result)
        return result

    try:
        candidate = candidate_builder(paths, observations, vx_contracts, target)
        receipt = _release_receipt(paths, target, candidate)
        snapshot_path = paths.daily_output_dir / f"{target.date().isoformat()}.json"
        existing = read_json(snapshot_path) if snapshot_path.exists() else None
        snapshot_changed = existing != candidate.payload
        _write_parquet_if_changed(candidate.features, paths.features)
        _write_parquet_if_changed(candidate.states, paths.states)
        if candidate.cache_action != "EXACT_CACHE_HIT":
            persist_probability_artifacts(
                paths,
                candidate.targets,
                candidate.oof,
                candidate.probability_contract,
            )
        if snapshot_changed:
            persist_snapshot(
                paths,
                candidate.payload,
                candidate.metadata,
                pd.DataFrame(),
                pd.DataFrame(),
            )
        else:
            write_json(candidate.metadata, paths.probability_metadata)
        receipt = with_snapshot_publication_binding(receipt, snapshot_path)
        receipt_path = acceptance_receipt_path(paths, target)
        receipt_changed = not _receipt_is_current(receipt_path, snapshot_path, receipt)
        if receipt_changed:
            receipt_writer(receipt, receipt_path)
            if not _receipt_is_current(receipt_path, snapshot_path, receipt):
                raise DailyAcceptanceError("acceptance receipt was not durably published last")
        if snapshot_changed or receipt_changed:
            status = DailyUpdateStatus.PUBLISHED
            message = f"published accepted daily snapshot and receipt for {target.date()}"
        else:
            status = DailyUpdateStatus.ALREADY_CURRENT
            message = f"accepted daily snapshot and receipt already current for {target.date()}"
        result = _result(
            status=status,
            now=current,
            target=target,
            report=report,
            refresh=refresh_result,
            last_good=target.date().isoformat(),
            message=message,
            snapshot_path=snapshot_path,
        )
    except Exception as exc:
        result = _result(
            status=DailyUpdateStatus.FAILED,
            now=current,
            target=target,
            report=report,
            refresh=refresh_result,
            last_good=previous_last_good,
            message=f"daily candidate failed; last-good preserved: {type(exc).__name__}: {exc}",
        )
    write_update_status(paths.root, result)
    return result


def run_daily_update(
    project_dir: str | Path,
    target_session: pd.Timestamp | str,
    *,
    now: datetime | None = None,
    refresh: RefreshHook | None = None,
    manifest: SourceManifest | None = None,
    candidate_builder: CandidateBuilder = build_daily_candidate,
    receipt_writer: ReceiptWriter = write_real_acceptance_report,
) -> DailyUpdateResult:
    """Run one project-scoped update without allowing overlapping publishers."""

    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    target = pd.Timestamp(target_session).normalize()
    if not is_session(target):
        raise ValueError(f"target is not an XNYS session: {target.date()}")
    paths = ProjectPaths(Path(project_dir).resolve())
    try:
        with project_publication_lock(paths.root, target, current=current):
            return _run_daily_update_locked(
                paths.root,
                target,
                now=current,
                refresh=refresh,
                manifest=manifest,
                candidate_builder=candidate_builder,
                receipt_writer=receipt_writer,
            )
    except ProjectPublicationBusyError:
        return DailyUpdateResult(
            status=DailyUpdateStatus.BUSY,
            updated_at=current.astimezone(UTC).isoformat(),
            target_session=target.date().isoformat(),
            latest_complete_session=None,
            last_good_session=last_good_session(paths),
            sources={},
            message="another MatVIX daily update already holds the project publication lock",
        )
