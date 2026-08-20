from __future__ import annotations

from datetime import datetime

import pandas as pd

from matvix.calendar import sessions_in_range
from matvix.data.point_in_time import filter_as_of, pit_evidence_for_vintage

REQUIRED_CORE_SERIES = (
    "VIX_OPEN",
    "VIX_HIGH",
    "VIX_LOW",
    "VIX_CLOSE",
    "VIX9D_CLOSE",
    "VIX3M_CLOSE",
    "VIX6M_CLOSE",
    "VVIX_CLOSE",
    "SKEW_CLOSE",
    "SPX_CLOSE",
)

SERIES_TO_COLUMN = {
    "VIX_OPEN": "vix_open",
    "VIX_HIGH": "vix_high",
    "VIX_LOW": "vix_low",
    "VIX_CLOSE": "vix_close",
    "VIX9D_CLOSE": "vix9d_close",
    "VIX3M_CLOSE": "vix3m_close",
    "VIX6M_CLOSE": "vix6m_close",
    "VVIX_CLOSE": "vvix_close",
    "SKEW_CLOSE": "skew_close",
    "SPX_CLOSE": "spx_close",
}


def observations_to_wide(observations: pd.DataFrame, as_of: datetime | None = None) -> pd.DataFrame:
    frame = observations.copy()
    if as_of is not None:
        frame = filter_as_of(frame, as_of)
    frame = frame.loc[frame["series_id"].isin(SERIES_TO_COLUMN)]
    if frame.empty:
        return pd.DataFrame(columns=["session_date", *SERIES_TO_COLUMN.values()])
    frame["session_date"] = pd.to_datetime(frame["session_date"]).dt.normalize()
    wide = frame.pivot(index="session_date", columns="series_id", values="value")
    wide = wide.rename(columns=SERIES_TO_COLUMN)
    for column in SERIES_TO_COLUMN.values():
        if column not in wide.columns:
            wide[column] = float("nan")
    return wide.reset_index()[["session_date", *SERIES_TO_COLUMN.values()]].sort_values(
        "session_date"
    )


def daily_vintage_summary(observations: pd.DataFrame) -> pd.DataFrame:
    frame = observations.copy()
    frame["session_date"] = pd.to_datetime(frame["session_date"]).dt.normalize()
    frame = frame.loc[frame["series_id"].isin(REQUIRED_CORE_SERIES)]
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "session_date",
                "source_rows",
                "raw_series_count",
                "raw_core_complete",
                "raw_formal_vintage_eligible",
                "raw_vintage_kind",
                "raw_pit_evidence",
                "raw_methodology_signature",
            ]
        )
    official_sessions = sessions_in_range(
        frame["session_date"].min().date(), frame["session_date"].max().date()
    )
    ranking = {"PROVIDER_BACKTESTED": 0, "ASSUMED_PIT": 1, "OBSERVED_PIT": 2}
    frame["_rank"] = frame["vintage_kind"].map(ranking)
    grouped = frame.groupby("session_date", as_index=False).agg(
        source_rows=("series_id", "count"),
        raw_series_count=("series_id", "nunique"),
        minimum_vintage_rank=("_rank", "min"),
    )
    grouped = (
        grouped.set_index("session_date")
        .reindex(official_sessions)
        .rename_axis("session_date")
        .reset_index()
    )
    grouped["source_rows"] = grouped["source_rows"].fillna(0).astype(int)
    grouped["raw_series_count"] = grouped["raw_series_count"].fillna(0).astype(int)
    grouped["raw_core_complete"] = grouped["raw_series_count"].eq(len(REQUIRED_CORE_SERIES))
    grouped["raw_formal_vintage_eligible"] = grouped["raw_core_complete"] & grouped[
        "minimum_vintage_rank"
    ].ge(1)
    grouped["raw_vintage_kind"] = grouped["minimum_vintage_rank"].map(
        {0: "PROVIDER_BACKTESTED", 1: "ASSUMED_PIT", 2: "OBSERVED_PIT"}
    )
    grouped["raw_pit_evidence"] = grouped["raw_vintage_kind"].map(pit_evidence_for_vintage)

    methodology = (
        frame.sort_values("session_date", kind="stable")
        .drop_duplicates(["session_date", "series_id"], keep="last")
        .pivot(index="session_date", columns="series_id", values="methodology_version")
        .reindex(index=official_sessions, columns=list(REQUIRED_CORE_SERIES))
        .ffill()
    )
    grouped["raw_methodology_signature"] = [
        (
            "|".join(f"{series_id}={row[series_id]}" for series_id in sorted(REQUIRED_CORE_SERIES))
            if row.notna().all()
            else None
        )
        for _, row in methodology.iterrows()
    ]
    return grouped.drop(columns="minimum_vintage_rank")
