from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

import pandas as pd

from matvix.constants import VintageKind


@dataclass(frozen=True)
class SourceIdentity:
    source: str
    source_symbol: str
    vintage_kind: str


_ASSUMED_PIT = VintageKind.ASSUMED_PIT.value

OFFICIAL_OBSERVATION_IDENTITIES: Final[Mapping[str, SourceIdentity]] = MappingProxyType(
    {
        "VIX_OPEN": SourceIdentity("CBOE", "VIX", _ASSUMED_PIT),
        "VIX_HIGH": SourceIdentity("CBOE", "VIX", _ASSUMED_PIT),
        "VIX_LOW": SourceIdentity("CBOE", "VIX", _ASSUMED_PIT),
        "VIX_CLOSE": SourceIdentity("CBOE", "VIX", _ASSUMED_PIT),
        "VIX9D_CLOSE": SourceIdentity("CBOE", "VIX9D", _ASSUMED_PIT),
        "VIX3M_CLOSE": SourceIdentity("CBOE", "VIX3M", _ASSUMED_PIT),
        "VIX6M_CLOSE": SourceIdentity("CBOE", "VIX6M", _ASSUMED_PIT),
        "VVIX_CLOSE": SourceIdentity("CBOE", "VVIX", _ASSUMED_PIT),
        "SKEW_CLOSE": SourceIdentity("CBOE", "SKEW", _ASSUMED_PIT),
        "SPX_CLOSE": SourceIdentity("CBOE", "SPX", _ASSUMED_PIT),
    }
)

VX_SETTLE_IDENTITY: Final[SourceIdentity] = SourceIdentity(
    "CFE", "VX_STANDARD_MONTHLY", _ASSUMED_PIT
)

OFFICIAL_SOURCE_IDENTITIES: Final[Mapping[str, SourceIdentity]] = MappingProxyType(
    {**OFFICIAL_OBSERVATION_IDENTITIES, "VX_SETTLE": VX_SETTLE_IDENTITY}
)


def _admit_identities(
    frame: pd.DataFrame, identities: Mapping[str, SourceIdentity]
) -> pd.DataFrame:
    """Return only rows whose full source identity matches the frozen policy."""

    if frame.empty:
        return frame.copy()
    required = {"series_id", "source", "source_symbol", "vintage_kind"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Missing source identity columns: {sorted(missing)}")

    admitted = pd.Series(False, index=frame.index, dtype=bool)
    for series_id, identity in identities.items():
        admitted |= (
            frame["series_id"].eq(series_id)
            & frame["source"].eq(identity.source)
            & frame["source_symbol"].eq(identity.source_symbol)
            & frame["vintage_kind"].eq(identity.vintage_kind)
        )
    return frame.loc[admitted].copy()


def admit_official_observations(frame: pd.DataFrame) -> pd.DataFrame:
    return _admit_identities(frame, OFFICIAL_OBSERVATION_IDENTITIES)


def admit_official_vx_settlements(frame: pd.DataFrame) -> pd.DataFrame:
    return _admit_identities(frame, {"VX_SETTLE": VX_SETTLE_IDENTITY})
