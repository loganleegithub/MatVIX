from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from matvix.calendar import decision_as_of, observed_at_eod
from matvix.constants import FORMAL_VINTAGES, VINTAGE_RANK, VintageKind


@dataclass(frozen=True)
class RawObservation:
    series_id: str
    session_date: str
    value: float
    unit: str
    source: str
    source_symbol: str
    observed_at: str
    available_at: str
    ingested_at: str
    revision_id: str
    methodology_version: str
    vintage_kind: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_REVISION_TIMING_COLUMNS = {"available_at", "ingested_at", "revision_id"}


def _canonical_value(value: object) -> object:
    if isinstance(value, (datetime, pd.Timestamp)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def content_revision_id(**semantic_fields: object) -> str:
    """Return a stable identity for one semantic observation, not its source file."""

    canonical = {key: _canonical_value(value) for key, value in sorted(semantic_fields.items())}
    encoded = json.dumps(
        canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def pit_evidence_for_vintage(vintage_kind: str | None) -> str:
    return {
        VintageKind.OBSERVED_PIT.value: "OBSERVED",
        VintageKind.ASSUMED_PIT.value: "ASSUMED",
        VintageKind.PROVIDER_BACKTESTED.value: "RESEARCH_ONLY",
    }.get(str(vintage_kind), "UNKNOWN")


def weakest_vintage(kinds: Iterable[str]) -> str | None:
    values = list(kinds)
    if not values:
        return None
    unknown = [value for value in values if value not in VINTAGE_RANK]
    if unknown:
        raise ValueError(f"Unknown vintage kinds: {unknown}")
    return min(values, key=VINTAGE_RANK.__getitem__)


def formal_vintage_eligible(kinds: Iterable[str]) -> bool:
    values = list(kinds)
    return bool(values) and all(value in FORMAL_VINTAGES for value in values)


def make_assumed_pit_observation(
    *,
    series_id: str,
    session_date: pd.Timestamp | str,
    value: float,
    unit: str,
    source: str,
    source_symbol: str,
    revision_id: str | None = None,
    ingested_at: datetime,
    methodology_version: str = "official_eod_v1",
) -> RawObservation:
    session = pd.Timestamp(session_date).date().isoformat()
    revision = revision_id or content_revision_id(
        series_id=series_id,
        session_date=session,
        value=float(value),
        unit=unit,
        source=source,
        source_symbol=source_symbol,
        methodology_version=methodology_version,
        vintage_kind=VintageKind.ASSUMED_PIT.value,
    )
    return RawObservation(
        series_id=series_id,
        session_date=session,
        value=float(value),
        unit=unit,
        source=source,
        source_symbol=source_symbol,
        observed_at=observed_at_eod(session).isoformat(),
        available_at=decision_as_of(session).isoformat(),
        ingested_at=ingested_at.isoformat(),
        revision_id=revision,
        methodology_version=methodology_version,
        vintage_kind=VintageKind.ASSUMED_PIT.value,
    )


def _utc_timestamp(value: object) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _semantic_fingerprint(row: pd.Series, columns: list[str]) -> str:
    return content_revision_id(**{column: row.get(column) for column in columns})


def merge_revision_history(
    existing: pd.DataFrame,
    incoming: pd.DataFrame,
    *,
    entity_columns: Iterable[str],
) -> pd.DataFrame:
    """Append new semantic revisions while preserving when they first became known.

    Import adapters assign the documented next-session availability to official
    historical rows.  On a later import, an unchanged row is retained exactly once;
    a changed row is appended and cannot become effective before that import's
    ``ingested_at`` timestamp.
    """

    entities = list(entity_columns)
    if existing.empty:
        return incoming.copy().reset_index(drop=True)
    if incoming.empty:
        return existing.copy().reset_index(drop=True)
    required = {
        *entities,
        "session_date",
        "available_at",
        "ingested_at",
        "revision_id",
        "vintage_kind",
    }
    for name, frame in (("existing", existing), ("incoming", incoming)):
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"Missing revision columns in {name}: {sorted(missing)}")

    all_columns = list(dict.fromkeys([*existing.columns, *incoming.columns]))
    semantic_columns = sorted(set(all_columns) - _REVISION_TIMING_COLUMNS)
    history = existing.reindex(columns=all_columns).copy()
    additions = incoming.reindex(columns=all_columns).copy()
    history["session_date"] = pd.to_datetime(history["session_date"]).dt.normalize()
    additions["session_date"] = pd.to_datetime(additions["session_date"]).dt.normalize()
    key_columns = [*entities, "session_date"]
    history["_semantic_fingerprint"] = history.apply(
        _semantic_fingerprint, axis=1, columns=semantic_columns
    )
    additions["_semantic_fingerprint"] = additions.apply(
        _semantic_fingerprint, axis=1, columns=semantic_columns
    )

    known_semantics = set(history["_semantic_fingerprint"].astype(str))
    known_keys = {
        tuple(_canonical_value(row[column]) for column in key_columns)
        for _, row in history.iterrows()
    }
    accepted: list[pd.Series] = []
    for _, row in additions.iterrows():
        fingerprint = str(row["_semantic_fingerprint"])
        if fingerprint in known_semantics:
            continue
        key = tuple(_canonical_value(row[column]) for column in key_columns)
        if key in known_keys:
            available = _utc_timestamp(row["available_at"])
            ingested = _utc_timestamp(row["ingested_at"])
            row["available_at"] = max(available, ingested).isoformat()
        accepted.append(row)
        known_semantics.add(fingerprint)
        known_keys.add(key)

    if accepted:
        accepted_frame = pd.DataFrame(accepted).reindex(columns=history.columns)
        history = pd.concat([history, accepted_frame], ignore_index=True)
    history["_available_sort"] = history["available_at"].map(_utc_timestamp)
    history["_ingested_sort"] = history["ingested_at"].map(_utc_timestamp)
    history = history.sort_values(
        [*key_columns, "_available_sort", "_ingested_sort", "revision_id"],
        kind="stable",
    )
    return history.drop(
        columns=["_semantic_fingerprint", "_available_sort", "_ingested_sort"]
    ).reset_index(drop=True)


def filter_as_of(observations: pd.DataFrame, as_of: datetime) -> pd.DataFrame:
    required = {"available_at", "vintage_kind", "series_id", "session_date", "revision_id"}
    missing = required - set(observations.columns)
    if missing:
        raise ValueError(f"Missing PIT columns: {sorted(missing)}")
    frame = observations.copy()
    frame["available_at"] = pd.to_datetime(frame["available_at"], format="mixed", utc=True)
    cutoff = _utc_timestamp(as_of)
    frame = frame.loc[frame["available_at"] <= cutoff]
    frame = frame.loc[frame["vintage_kind"].isin(FORMAL_VINTAGES)]
    sort_columns = ["series_id", "session_date", "available_at"]
    if "ingested_at" in frame.columns:
        frame["ingested_at"] = pd.to_datetime(
            frame["ingested_at"], format="mixed", utc=True
        )
        sort_columns.append("ingested_at")
    sort_columns.append("revision_id")
    frame = frame.sort_values(sort_columns, kind="stable")
    return frame.drop_duplicates(["series_id", "session_date"], keep="last").reset_index(drop=True)


def select_historical_point_in_time(
    frame: pd.DataFrame,
    *,
    entity_columns: Iterable[str],
    formal_only: bool = True,
) -> pd.DataFrame:
    """Select the revision that was available at each session's decision timestamp.

    This is the formal-history equivalent of ``filter_as_of``.  It evaluates every
    row against ``decision_as_of(row.session_date)`` so a later vendor revision
    cannot leak backward into percentiles, labels, training, OOF, or calibration.
    ``PROVIDER_BACKTESTED`` rows are excluded from the formal chain by default.
    """

    required = {
        "session_date",
        "available_at",
        "vintage_kind",
        "revision_id",
        *entity_columns,
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Missing historical PIT columns: {sorted(missing)}")
    selected = frame.copy()
    selected["session_date"] = pd.to_datetime(selected["session_date"]).dt.normalize()
    selected["available_at"] = pd.to_datetime(
        selected["available_at"], format="mixed", utc=True
    )
    selected["_decision_as_of"] = selected["session_date"].map(
        lambda session: pd.Timestamp(decision_as_of(session)).tz_convert("UTC")
    )
    selected = selected.loc[selected["available_at"] <= selected["_decision_as_of"]]
    if formal_only:
        selected = selected.loc[selected["vintage_kind"].isin(FORMAL_VINTAGES)]
    keys = [*entity_columns, "session_date"]
    sort_columns = [*keys, "available_at"]
    if "ingested_at" in selected.columns:
        selected["ingested_at"] = pd.to_datetime(
            selected["ingested_at"], format="mixed", utc=True
        )
        sort_columns.append("ingested_at")
    sort_columns.append("revision_id")
    selected = selected.sort_values(sort_columns, kind="stable")
    selected = selected.drop_duplicates(keys, keep="last")
    return selected.drop(columns="_decision_as_of").reset_index(drop=True)


def reject_research_only(frame: pd.DataFrame) -> None:
    if "vintage_kind" not in frame.columns:
        raise ValueError("vintage_kind is required")
    bad = frame.loc[~frame["vintage_kind"].isin(FORMAL_VINTAGES)]
    if not bad.empty:
        raise ValueError(
            f"Formal chain rejected {len(bad)} PROVIDER_BACKTESTED/unknown observations"
        )
