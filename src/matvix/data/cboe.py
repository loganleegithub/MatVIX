from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pandas as pd
import requests

from matvix.data.point_in_time import make_assumed_pit_observation

CBOE_HISTORY_URL: Final[str] = (
    "https://cdn.cboe.com/api/global/us_indices/daily_prices/{symbol}_History.csv"
)
SUPPORTED_SYMBOLS = ("VIX", "VIX9D", "VIX3M", "VIX6M", "VVIX", "SKEW")


def download_cboe_history(symbol: str, output_dir: str | Path, timeout: int = 60) -> Path:
    symbol = symbol.upper()
    if symbol not in SUPPORTED_SYMBOLS:
        raise ValueError(f"Unsupported Cboe series: {symbol}")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"{symbol}_History.csv"
    url = CBOE_HISTORY_URL.format(symbol=symbol)
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "MatVIX/1.0"})
    response.raise_for_status()
    if not response.content.startswith(b"DATE"):
        raise ValueError(f"Unexpected Cboe payload for {symbol}")
    target.write_bytes(response.content)
    return target


def download_cboe_core(output_dir: str | Path) -> list[Path]:
    return [download_cboe_history(symbol, output_dir) for symbol in SUPPORTED_SYMBOLS]


def _normalize_cboe_frame(path: Path, symbol: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame.columns = [str(column).strip().upper() for column in frame.columns]
    if "DATE" not in frame.columns:
        raise ValueError(f"DATE column missing in {path}")
    frame["DATE"] = pd.to_datetime(frame["DATE"], errors="raise").dt.normalize()
    frame = frame.sort_values("DATE").drop_duplicates("DATE", keep="last")
    if symbol == "VIX":
        expected = {"OPEN", "HIGH", "LOW", "CLOSE"}
        if not expected.issubset(frame.columns):
            raise ValueError(f"VIX OHLC columns missing in {path}")
        return frame[["DATE", "OPEN", "HIGH", "LOW", "CLOSE"]]
    value_column = "CLOSE" if "CLOSE" in frame.columns else symbol
    if value_column not in frame.columns:
        candidates = [c for c in frame.columns if c != "DATE"]
        if len(candidates) != 1:
            raise ValueError(f"Cannot identify value column in {path}: {candidates}")
        value_column = candidates[0]
    return frame[["DATE", value_column]].rename(columns={value_column: "CLOSE"})


def import_cboe_history(
    path: str | Path, symbol: str, ingested_at: datetime | None = None
) -> pd.DataFrame:
    source_path = Path(path)
    symbol = symbol.upper()
    if symbol not in SUPPORTED_SYMBOLS:
        raise ValueError(f"Unsupported Cboe symbol: {symbol}")
    ingested_at = ingested_at or datetime.now(UTC)
    frame = _normalize_cboe_frame(source_path, symbol)
    rows: list[dict[str, object]] = []
    if symbol == "VIX":
        for record in frame.itertuples(index=False):
            for field, value in zip(("OPEN", "HIGH", "LOW", "CLOSE"), record[1:], strict=True):
                if pd.isna(value):
                    continue
                observation = make_assumed_pit_observation(
                    series_id=f"VIX_{field}",
                    session_date=record.DATE,
                    value=float(value),
                    unit="index_points",
                    source="CBOE",
                    source_symbol="VIX",
                    ingested_at=ingested_at,
                    methodology_version="CBOE_VIX_OFFICIAL_EOD",
                )
                rows.append(observation.as_dict())
    else:
        series_id = f"{symbol}_CLOSE"
        for record in frame.itertuples(index=False):
            if pd.isna(record.CLOSE):
                continue
            observation = make_assumed_pit_observation(
                series_id=series_id,
                session_date=record.DATE,
                value=float(record.CLOSE),
                unit="index_points",
                source="CBOE",
                source_symbol=symbol,
                ingested_at=ingested_at,
                methodology_version=f"CBOE_{symbol}_OFFICIAL_EOD",
            )
            rows.append(observation.as_dict())
    return pd.DataFrame(rows)


def import_cboe_directory(directory: str | Path) -> pd.DataFrame:
    root = Path(directory)
    frames: list[pd.DataFrame] = []
    for symbol in SUPPORTED_SYMBOLS:
        path = root / f"{symbol}_History.csv"
        if path.exists():
            frames.append(import_cboe_history(path, symbol))
    if not frames:
        raise FileNotFoundError(f"No supported Cboe history files in {root}")
    return pd.concat(frames, ignore_index=True).sort_values(["session_date", "series_id"])
