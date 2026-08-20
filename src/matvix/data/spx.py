from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from matvix.data.point_in_time import make_assumed_pit_observation


def import_spx_close(
    path: str | Path,
    *,
    source: str = "LOCAL_AUTHORIZED_IMPORT",
    source_symbol: str = "SPX",
    ingested_at: datetime | None = None,
) -> pd.DataFrame:
    source_path = Path(path)
    frame = pd.read_csv(source_path)
    canonical = {str(column).strip().upper(): column for column in frame.columns}
    is_fred_sp500 = "OBSERVATION_DATE" in canonical and "SP500" in canonical
    if is_fred_sp500:
        date_column = canonical["OBSERVATION_DATE"]
        close_column = canonical["SP500"]
        if source == "LOCAL_AUTHORIZED_IMPORT":
            source = "FRED"
        if source_symbol == "SPX":
            source_symbol = "SP500"
        methodology_version = "FRED_SP500_DAILY_CLOSE_V1"
    else:
        date_column = canonical.get("DATE")
        close_column = canonical.get("CLOSE") or canonical.get("SPX") or canonical.get("VALUE")
        methodology_version = "SPX_OFFICIAL_OR_AUTHORIZED_CLOSE_V1"
    if date_column is None or close_column is None:
        raise ValueError(
            "SPX import requires DATE,CLOSE (or SPX/VALUE), or FRED observation_date,SP500"
        )
    frame = frame[[date_column, close_column]].rename(
        columns={date_column: "DATE", close_column: "CLOSE"}
    )
    frame["DATE"] = pd.to_datetime(frame["DATE"], errors="raise").dt.normalize()
    frame["CLOSE"] = pd.to_numeric(frame["CLOSE"], errors="coerce")
    frame = frame.dropna().sort_values("DATE").drop_duplicates("DATE", keep="last")
    ingested_at = ingested_at or datetime.now(UTC)
    rows = [
        make_assumed_pit_observation(
            series_id="SPX_CLOSE",
            session_date=row.DATE,
            value=float(row.CLOSE),
            unit="index_points",
            source=source,
            source_symbol=source_symbol,
            ingested_at=ingested_at,
            methodology_version=methodology_version,
        ).as_dict()
        for row in frame.itertuples(index=False)
    ]
    return pd.DataFrame(rows)
