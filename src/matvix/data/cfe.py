from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

from matvix.calendar import (
    decision_as_of,
    final_settlement_timestamp,
    observed_at_eod,
    vix_final_settlement_date,
)
from matvix.constants import VintageKind
from matvix.data.point_in_time import content_revision_id

CFE_CONTRACT_URL = (
    "https://cdn.cboe.com/data/us/futures/market_statistics/historical_data/VX/VX_{date}.csv"
)


def contract_url(year: int, month: int) -> str:
    return CFE_CONTRACT_URL.format(date=vix_final_settlement_date(year, month).isoformat())


def download_monthly_contract(
    year: int, month: int, output_dir: str | Path, timeout: int = 60
) -> Path | None:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    settlement_date = vix_final_settlement_date(year, month).isoformat()
    target = target_dir / f"VX_{settlement_date}.csv"
    response = requests.get(
        contract_url(year, month), timeout=timeout, headers={"User-Agent": "MatVIX/1.0"}
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    if b"Trade Date" not in response.content[:5000]:
        raise ValueError(f"Unexpected CFE payload for {year}-{month:02d}")
    target.write_bytes(response.content)
    return target


def download_monthly_history(start_year: int, end_year: int, output_dir: str | Path) -> list[Path]:
    paths: list[Path] = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            path = download_monthly_contract(year, month, output_dir)
            if path is not None:
                paths.append(path)
    return paths


def _settlement_date_from_filename(path: Path) -> pd.Timestamp:
    match = re.search(r"VX_(\d{4}-\d{2}-\d{2})", path.name)
    if not match:
        raise ValueError(f"CFE filename must contain VX_YYYY-MM-DD: {path.name}")
    return pd.Timestamp(match.group(1))


def parse_monthly_contract(path: str | Path, ingested_at: datetime | None = None) -> pd.DataFrame:
    source_path = Path(path)
    final_date = _settlement_date_from_filename(source_path)
    contract_year = int(final_date.year)
    contract_month = int(final_date.month)
    expected = pd.Timestamp(vix_final_settlement_date(contract_year, contract_month))
    if final_date != expected:
        actual_date = final_date.date()
        expected_date = expected.date()
        raise ValueError(
            f"File is not the standard monthly VX settlement date: {actual_date} != {expected_date}"
        )
    frame = pd.read_csv(source_path, skipinitialspace=True)
    frame.columns = [str(column).strip() for column in frame.columns]
    required = {"Trade Date", "Settle"}
    if not required.issubset(frame.columns):
        raise ValueError(
            f"Missing CFE columns {sorted(required - set(frame.columns))} in {source_path}"
        )
    frame["session_date"] = pd.to_datetime(frame["Trade Date"], errors="coerce").dt.normalize()
    frame["settle"] = pd.to_numeric(frame["Settle"], errors="coerce")
    frame = frame.dropna(subset=["session_date", "settle"])
    frame = frame.loc[frame["settle"].gt(0)].copy()
    ingested_at = ingested_at or datetime.now(UTC)
    futures_column = "Futures" if "Futures" in frame.columns else None
    contract_id_default = f"VX{contract_year:04d}{contract_month:02d}"
    result = pd.DataFrame(
        {
            "session_date": frame["session_date"],
            "contract_id": (
                frame[futures_column].astype(str).str.strip()
                if futures_column
                else contract_id_default
            ),
            "contract_year": contract_year,
            "contract_month": contract_month,
            "final_settlement_date": final_date,
            "final_settlement_timestamp": final_settlement_timestamp(
                contract_year, contract_month
            ).isoformat(),
            "settle": frame["settle"].astype(float),
            "unit": "vix_points",
            "source": "CFE",
            "source_symbol": "VX_STANDARD_MONTHLY",
            "series_id": "VX_SETTLE",
            "value": frame["settle"].astype(float),
            "observed_at": frame["session_date"].map(
                lambda value: observed_at_eod(pd.Timestamp(value)).isoformat()
            ),
            "available_at": frame["session_date"].map(
                lambda value: decision_as_of(pd.Timestamp(value)).isoformat()
            ),
            "ingested_at": ingested_at.isoformat(),
            "methodology_version": "CFE_VX_MONTHLY_OFFICIAL_SETTLEMENT_V1",
            "vintage_kind": VintageKind.ASSUMED_PIT.value,
            "is_standard_monthly": True,
        }
    )
    result["revision_id"] = result.apply(
        lambda row: content_revision_id(
            series_id=row["series_id"],
            session_date=row["session_date"],
            contract_id=row["contract_id"],
            settle=row["settle"],
            final_settlement_timestamp=row["final_settlement_timestamp"],
            unit=row["unit"],
            source=row["source"],
            source_symbol=row["source_symbol"],
            methodology_version=row["methodology_version"],
            vintage_kind=row["vintage_kind"],
        ),
        axis=1,
    )
    return result.sort_values("session_date").drop_duplicates(
        ["session_date", "contract_id"], keep="last"
    )


def import_cfe_directory(directory: str | Path) -> pd.DataFrame:
    root = Path(directory)
    frames: list[pd.DataFrame] = []
    ingested_at = datetime.now(UTC)
    for path in sorted(root.glob("VX_????-??-??.csv")):
        final_date = _settlement_date_from_filename(path)
        expected = pd.Timestamp(vix_final_settlement_date(final_date.year, final_date.month))
        if final_date != expected:
            # Weekly expiries may share the vendor filename pattern; reject only
            # those known non-standard dates, not malformed standard-month files.
            continue
        parsed = parse_monthly_contract(path, ingested_at=ingested_at)
        if not parsed.empty:
            frames.append(parsed)
    if not frames:
        raise FileNotFoundError(f"No valid standard monthly VX files in {root}")
    return pd.concat(frames, ignore_index=True).sort_values(
        ["session_date", "final_settlement_date"]
    )
