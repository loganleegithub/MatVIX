from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from matvix.calendar import add_sessions, decision_as_of
from matvix.constants import EVENT_ORDER
from matvix.data.assemble import REQUIRED_CORE_SERIES
from matvix.data.point_in_time import select_historical_point_in_time
from matvix.features.percentile import rolling_midrank_percentile
from matvix.pipeline import build_state_history
from matvix.probability.calibration import acceptance_metrics, brier_score
from matvix.probability.engine import prepare_probability_artifacts, run_probability_job
from matvix.storage import read_json, read_parquet, write_json, write_parquet

AUDIT_VERSION = "1.0.0"
CHICAGO = ZoneInfo("America/Chicago")
DEVELOPMENT_END = pd.Timestamp("2021-12-31")
CONFIRMATION_START = pd.Timestamp("2022-01-03")
APPEND_INVARIANCE_CUTOFF = pd.Timestamp("2024-12-31")

BASELINE_FILES = {
    "features": "v1_features.parquet",
    "states": "v1_states.parquet",
    "targets": "v1_targets.parquet",
    "oof": "v1_oof.parquet",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _date_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    return cast(str, pd.Timestamp(value).date().isoformat())


def _finite(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(cast(Any, value))
    return number if np.isfinite(number) else None


def _as_list(value: object) -> list[object]:
    if isinstance(value, np.ndarray):
        return cast(list[object], value.tolist())
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _verify_frozen_baseline(root: Path) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    baseline = root / "outputs" / "v2_baseline"
    manifest = read_json(baseline / "v1_manifest.json")
    tables: dict[str, pd.DataFrame] = {}
    errors: list[str] = []
    manifest_tables = manifest.get("tables", {})
    if not isinstance(manifest_tables, dict):
        raise ValueError("V1 baseline manifest tables must be an object")
    for name, filename in BASELINE_FILES.items():
        path = baseline / filename
        entry = manifest_tables.get(name)
        if not isinstance(entry, dict):
            errors.append(f"{name}: manifest entry missing")
            continue
        actual_hash = _sha256(path)
        if actual_hash != entry.get("sha256"):
            errors.append(f"{name}: SHA-256 mismatch")
        frame = read_parquet(path)
        if len(frame) != int(entry.get("rows", -1)):
            errors.append(f"{name}: row count mismatch")
        tables[name] = frame
    if errors:
        raise ValueError("Frozen V1 baseline verification failed: " + "; ".join(errors))
    return manifest, tables


def _month_is_next(left_year: int, left_month: int, right_year: int, right_month: int) -> bool:
    return right_year * 12 + right_month == left_year * 12 + left_month + 1


def curve_audit_record(curve: pd.DataFrame, session_date: pd.Timestamp | str) -> dict[str, Any]:
    """Calculate independent F1-F7 and 30-day facts for one already-PIT-selected session."""

    session = pd.Timestamp(session_date).normalize()
    cutoff = pd.Timestamp(datetime.combine(session.date(), time(15, 0), tzinfo=CHICAGO))
    frame = curve.copy()
    if frame.empty:
        frame = pd.DataFrame(columns=["settle", "final_settlement_timestamp"])
    if "is_standard_monthly" in frame:
        frame = frame.loc[frame["is_standard_monthly"].fillna(False)]
    frame["settle"] = pd.to_numeric(frame.get("settle"), errors="coerce")
    frame["_final_ts"] = pd.to_datetime(
        frame.get("final_settlement_timestamp"), utc=True, errors="coerce"
    ).dt.tz_convert(CHICAGO)
    frame = frame.loc[
        frame["settle"].gt(0) & frame["_final_ts"].notna() & frame["_final_ts"].gt(cutoff)
    ]
    frame = (
        frame.sort_values(["_final_ts", "contract_id"], kind="stable")
        .drop_duplicates("_final_ts", keep="last")
        .head(7)
        .reset_index(drop=True)
    )
    settles = frame["settle"].to_numpy(dtype=float)
    days = np.asarray(
        [(timestamp - cutoff).total_seconds() / 86400 for timestamp in frame["_final_ts"]],
        dtype=float,
    )
    identifiers = frame.get("contract_id", pd.Series(dtype=str)).astype(str).tolist()
    years = pd.to_numeric(frame.get("contract_year"), errors="coerce").tolist()
    months = pd.to_numeric(frame.get("contract_month"), errors="coerce").tolist()
    sequential = len(frame) == 7 and all(
        _month_is_next(
            int(years[index]), int(months[index]), int(years[index + 1]), int(months[index + 1])
        )
        for index in range(6)
        if pd.notna(years[index])
        and pd.notna(months[index])
        and pd.notna(years[index + 1])
        and pd.notna(months[index + 1])
    )

    strict = np.nan
    bracket_index: int | None = None
    for index in range(len(frame) - 1):
        if days[index] <= 30.0 < days[index + 1] and days[index + 1] > days[index]:
            strict = settles[index] + (settles[index + 1] - settles[index]) * (
                (30.0 - days[index]) / (days[index + 1] - days[index])
            )
            bracket_index = index
            break

    bounded = np.nan
    if len(frame) >= 2 and 30.0 < days[0] <= 36.0 and days[1] > days[0]:
        bounded = settles[0] + (settles[1] - settles[0]) * ((30.0 - days[0]) / (days[1] - days[0]))

    pseudo = np.nan
    if len(frame) >= 3 and bracket_index == 0 and days[1] > 30.0 and days[2] > days[1]:
        pseudo = settles[1] + (settles[2] - settles[1]) * ((30.0 - days[1]) / (days[2] - days[1]))

    result: dict[str, Any] = {
        "session_date": session,
        "f1_f7_count": int(len(frame)),
        "f1_f7_sequential": bool(sequential),
        "f1_f7_contract_ids": identifiers,
        "strict_vxcm30": float(strict) if np.isfinite(strict) else np.nan,
        "strict_vxcm30_bracket_index": bracket_index,
        "bounded_vxcm30_candidate": float(bounded) if np.isfinite(bounded) else np.nan,
        "pseudo_gap_vxcm30": float(pseudo) if np.isfinite(pseudo) else np.nan,
    }
    for index in range(7):
        result[f"f{index + 1}_settle"] = settles[index] if index < len(settles) else np.nan
        result[f"f{index + 1}_days"] = days[index] if index < len(days) else np.nan
    return result


def _build_curve_audit(vx_contracts: pd.DataFrame, sessions: pd.Series) -> pd.DataFrame:
    admitted = select_historical_point_in_time(
        vx_contracts, entity_columns=["contract_id"], formal_only=True
    )
    admitted["session_date"] = pd.to_datetime(admitted["session_date"]).dt.normalize()
    groups = {session: frame for session, frame in admitted.groupby("session_date", sort=False)}
    empty = admitted.iloc[0:0]
    return pd.DataFrame(
        [
            curve_audit_record(groups.get(pd.Timestamp(session).normalize(), empty), session)
            for session in sessions
        ]
    )


def _add_observation_audit(
    ledger: pd.DataFrame, observations: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    raw = observations.copy()
    raw["session_date"] = pd.to_datetime(raw["session_date"]).dt.normalize()
    raw["value"] = pd.to_numeric(raw["value"], errors="coerce")
    admitted = select_historical_point_in_time(raw, entity_columns=["series_id"], formal_only=True)
    admitted = admitted.loc[admitted["series_id"].isin(REQUIRED_CORE_SERIES)].copy()
    daily_records: list[dict[str, Any]] = []
    for session, frame in admitted.groupby("session_date", sort=False):
        present = set(frame["series_id"].astype(str))
        daily_records.append(
            {
                "session_date": session,
                "raw_core_series_count": len(present),
                "raw_core_missing_series": sorted(set(REQUIRED_CORE_SERIES) - present),
                "raw_core_nonpositive_count": int(frame["value"].le(0).sum()),
                "raw_core_vintages": sorted(set(frame["vintage_kind"].astype(str))),
                "raw_core_methodologies": sorted(set(frame["methodology_version"].astype(str))),
                "raw_core_selected_after_decision_count": int(
                    sum(
                        pd.Timestamp(value).tz_convert("UTC")
                        > pd.Timestamp(decision_as_of(session)).tz_convert("UTC")
                        for value in pd.to_datetime(frame["available_at"], utc=True)
                    )
                ),
            }
        )
    daily = pd.DataFrame(daily_records)
    result = ledger.merge(daily, on="session_date", how="left", validate="one_to_one")
    result["raw_core_series_count"] = result["raw_core_series_count"].fillna(0).astype(int)
    result["raw_core_missing_series"] = result["raw_core_missing_series"].map(
        lambda value: value if isinstance(value, list) else list(REQUIRED_CORE_SERIES)
    )
    series_summary: dict[str, Any] = {}
    for series_id in REQUIRED_CORE_SERIES:
        frame = raw.loc[raw["series_id"].eq(series_id)]
        series_summary[series_id] = {
            "rows": int(len(frame)),
            "sessions": int(frame["session_date"].nunique()),
            "first_session": _date_text(frame["session_date"].min()),
            "last_session": _date_text(frame["session_date"].max()),
            "duplicate_revision_keys": int(
                frame.duplicated(["series_id", "session_date", "revision_id"]).sum()
            ),
            "nonpositive": int(frame["value"].le(0).sum()),
            "vintages": sorted(set(frame["vintage_kind"].astype(str))),
            "methodologies": sorted(set(frame["methodology_version"].astype(str))),
        }
    summary = {
        "series": series_summary,
        "duplicate_revision_keys": int(
            raw.duplicated(["series_id", "session_date", "revision_id"]).sum()
        ),
        "nonpositive_values": int(raw["value"].le(0).sum()),
        "selected_after_decision": int(result["raw_core_selected_after_decision_count"].sum()),
    }
    return result, summary


def _add_tenor_candidates(ledger: pd.DataFrame) -> pd.DataFrame:
    result = ledger.copy()
    result["front_curve_level"] = result[["f1_settle", "f2_settle"]].mean(axis=1)
    result["f4_f7_level"] = result[["f4_settle", "f5_settle", "f6_settle", "f7_settle"]].mean(
        axis=1, skipna=False
    )
    result["f4_f7_slope30"] = (
        np.log(result["f7_settle"] / result["f4_settle"])
        * 30.0
        / (result["f7_days"] - result["f4_days"])
    )
    result["f4_f7_inversion_share"] = (
        result["f4_settle"].gt(result["f5_settle"]).astype(float)
        + result["f5_settle"].gt(result["f6_settle"]).astype(float)
        + result["f6_settle"].gt(result["f7_settle"]).astype(float)
    ) / 3.0
    result["front_to_mid_log_ratio"] = np.log(result["f4_f7_level"] / result["front_curve_level"])
    for horizon in (5, 10):
        result[f"d{horizon}_log_f4_f7_level"] = np.log(
            result["f4_f7_level"] / result["f4_f7_level"].shift(horizon)
        )
        result[f"d{horizon}_f4_f7_slope30"] = result["f4_f7_slope30"] - result[
            "f4_f7_slope30"
        ].shift(horizon)
        result[f"d{horizon}_f4_f7_inversion_share"] = result["f4_f7_inversion_share"] - result[
            "f4_f7_inversion_share"
        ].shift(horizon)
        result[f"fwd{horizon}_log_f4_f7_level"] = np.log(
            result["f4_f7_level"].shift(-horizon) / result["f4_f7_level"]
        )
        result[f"fwd{horizon}_f4_f7_slope30"] = (
            result["f4_f7_slope30"].shift(-horizon) - result["f4_f7_slope30"]
        )
        result[f"fwd{horizon}_f4_f7_inversion_share"] = (
            result["f4_f7_inversion_share"].shift(-horizon) - result["f4_f7_inversion_share"]
        )
    result["p_f4_f7_level"] = rolling_midrank_percentile(
        result["f4_f7_level"], reference_sessions=756, minimum_valid=504
    )

    observable = (
        result[
            [
                "p_f4_f7_level",
                "d5_log_f4_f7_level",
                "d5_f4_f7_slope30",
                "d5_f4_f7_inversion_share",
                "near_stress_log_ratio",
                "front_slope30",
            ]
        ]
        .notna()
        .all(axis=1)
    )
    front_pressure = result["near_stress_log_ratio"].gt(0) | result["front_slope30"].lt(0)
    priced = result["p_f4_f7_level"].ge(0.75) | result["f4_f7_inversion_share"].ge(2 / 3)
    rising = result["d5_log_f4_f7_level"].gt(0) & (
        result["d5_f4_f7_slope30"].lt(0) | result["d5_f4_f7_inversion_share"].gt(0)
    )
    prior_priced = priced.shift(1).rolling(10, min_periods=1).max().fillna(False).astype(bool)
    receding = (
        prior_priced
        & result["d5_log_f4_f7_level"].lt(0)
        & (result["d5_f4_f7_slope30"].gt(0) | result["d5_f4_f7_inversion_share"].lt(0))
    )
    mid_state = np.select(
        [receding, priced, rising], ["RECEDING", "PRICED", "RISING"], default="QUIET"
    ).astype(object)
    mid_state[~observable.to_numpy()] = "UNKNOWN"
    result["mid_curve_pressure_state_candidate"] = mid_state
    result["front_pressure_raw"] = front_pressure.where(observable)

    scope = np.select(
        [
            front_pressure & pd.Series(mid_state, index=result.index).isin(["RISING", "PRICED"]),
            ~front_pressure & pd.Series(mid_state, index=result.index).isin(["RISING", "PRICED"]),
            front_pressure,
        ],
        ["BROAD", "MID", "FRONT"],
        default="NONE",
    ).astype(object)
    scope[~observable.to_numpy()] = "UNKNOWN"
    result["stress_tenor_scope_candidate"] = scope
    stage = np.select(
        [
            pd.Series(mid_state, index=result.index).eq("RECEDING"),
            pd.Series(scope, index=result.index).eq("BROAD")
            & pd.Series(mid_state, index=result.index).eq("PRICED"),
            pd.Series(scope, index=result.index).eq("BROAD")
            & pd.Series(mid_state, index=result.index).eq("RISING"),
            pd.Series(scope, index=result.index).eq("FRONT"),
        ],
        ["RECEDING", "PRICED", "DIFFUSING", "FRONT_LOCALIZED"],
        default="NONE",
    ).astype(object)
    stage[~observable.to_numpy()] = "UNKNOWN"
    result["tenor_stage_candidate"] = stage

    result["vxcm30_audit_candidate"] = result["strict_vxcm30"].fillna(
        result["bounded_vxcm30_candidate"]
    )
    result["basis30_audit_candidate"] = result["vxcm30_audit_candidate"] / result["vix_close"] - 1.0
    carry_observable = result[
        [
            "front_slope30",
            "basis30_audit_candidate",
            "near_stress_log_ratio",
            "f4_f7_slope30",
        ]
    ].notna().all(axis=1) & pd.Series(mid_state, index=result.index).ne("UNKNOWN")
    carry_open_day = (
        result["front_slope30"].gt(0)
        & result["basis30_audit_candidate"].gt(0)
        & result["near_stress_log_ratio"].le(0)
        & result["f4_f7_slope30"].gt(0)
        & pd.Series(mid_state, index=result.index).eq("QUIET")
    ).where(carry_observable)
    open_confirmed = carry_open_day.eq(True) & carry_open_day.shift(1).eq(True)
    carry_state = np.select(
        [open_confirmed, carry_open_day.eq(True) | pd.Series(mid_state).eq("RECEDING")],
        ["OPEN", "RECOVERING"],
        default="CLOSED",
    ).astype(object)
    carry_state[~carry_observable.to_numpy()] = "UNKNOWN"
    result["carry_open_day_candidate"] = carry_open_day
    result["carry_environment_state_candidate"] = carry_state
    return result


def _split_name(dates: pd.Series) -> pd.Series:
    return pd.Series(
        np.where(dates <= DEVELOPMENT_END, "DEVELOPMENT", "CONFIRMATION"), index=dates.index
    )


def _distribution(values: pd.Series) -> dict[str, Any]:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return {"n": 0, "median": None, "q25": None, "q75": None, "positive_rate": None}
    return {
        "n": int(len(numeric)),
        "median": float(numeric.median()),
        "q25": float(numeric.quantile(0.25)),
        "q75": float(numeric.quantile(0.75)),
        "positive_rate": float(numeric.gt(0).mean()),
    }


def _conditional_weather(ledger: pd.DataFrame, group_column: str) -> dict[str, Any]:
    output: dict[str, Any] = {}
    facts = [
        "fwd5_log_f4_f7_level",
        "fwd10_log_f4_f7_level",
        "fwd5_f4_f7_slope30",
        "fwd10_f4_f7_slope30",
        "fwd5_f4_f7_inversion_share",
        "fwd10_f4_f7_inversion_share",
    ]
    eligible = ledger.loc[ledger["data_status"].eq("OK")].copy()
    for split, split_frame in eligible.groupby("audit_window"):
        groups: dict[str, Any] = {}
        for value, frame in split_frame.groupby(group_column):
            groups[str(value)] = {
                "sessions": int(len(frame)),
                **{fact: _distribution(frame[fact]) for fact in facts},
            }
        output[str(split)] = groups
    return output


def _cross_tab(ledger: pd.DataFrame, left: str, right: str) -> dict[str, Any]:
    frame = ledger.loc[ledger["data_status"].eq("OK")]
    counts = pd.crosstab(frame[left], frame[right])
    rates = pd.crosstab(frame[left], frame[right], normalize="index")
    return {
        str(index): {
            "sessions": int(counts.loc[index].sum()),
            "counts": {str(column): int(counts.loc[index, column]) for column in counts.columns},
            "rates": {str(column): float(rates.loc[index, column]) for column in rates.columns},
        }
        for index in counts.index
    }


def _true_clusters(dates: pd.Series, predicate: pd.Series) -> list[dict[str, Any]]:
    values = predicate.fillna(False).astype(bool).to_numpy()
    clusters: list[dict[str, Any]] = []
    start: int | None = None
    for index, value in enumerate(values):
        if value and start is None:
            start = index
        if start is not None and (not value or index == len(values) - 1):
            end = index if value and index == len(values) - 1 else index - 1
            clusters.append(
                {
                    "cluster_id": len(clusters) + 1,
                    "start_index": start,
                    "end_index": end,
                    "start_session": _date_text(dates.iloc[start]),
                    "end_session": _date_text(dates.iloc[end]),
                    "sessions": end - start + 1,
                }
            )
            start = None
    return clusters


def _mark_clusters(
    ledger: pd.DataFrame, name: str, predicate: pd.Series
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    result = ledger.copy()
    clusters = _true_clusters(result["session_date"], predicate)
    result[f"{name}__event"] = predicate
    result[f"{name}__cluster_id"] = pd.Series(pd.NA, index=result.index, dtype="Int64")
    result[f"{name}__start"] = False
    for cluster in clusters:
        start = int(cluster["start_index"])
        end = int(cluster["end_index"])
        result.loc[start:end, f"{name}__cluster_id"] = int(cluster["cluster_id"])
        result.loc[start, f"{name}__start"] = True
    return result, clusters


def _loco_direction(values: Iterable[float], expected_sign: int) -> dict[str, Any]:
    sample = np.asarray([value for value in values if np.isfinite(value)], dtype=float)
    if len(sample) < 3:
        return {"status": "INSUFFICIENT_EVIDENCE", "clusters": int(len(sample)), "rate": None}
    checks = []
    for index in range(len(sample)):
        median = float(np.median(np.delete(sample, index)))
        checks.append(median > 0 if expected_sign > 0 else median < 0)
    return {
        "status": "STABLE" if all(checks) else "UNSTABLE",
        "clusters": int(len(sample)),
        "rate": float(np.mean(checks)),
        "full_median": float(np.median(sample)),
    }


def _match_clusters(
    event_clusters: list[dict[str, Any]],
    signal_clusters: list[dict[str, Any]],
    *,
    lead_window: int,
    lag_window: int,
) -> dict[str, Any]:
    matched_signals: set[int] = set()
    leads: list[int] = []
    misses: list[dict[str, Any]] = []
    for event in event_clusters:
        event_start = int(event["start_index"])
        event_end = int(event["end_index"])
        candidates = [
            signal
            for signal in signal_clusters
            if int(signal["start_index"]) <= event_end + lag_window
            and int(signal["end_index"]) >= event_start - lead_window
        ]
        if not candidates:
            misses.append(event)
            continue
        selected = min(
            candidates,
            key=lambda signal: abs(event_start - int(signal["start_index"])),
        )
        matched_signals.add(int(selected["cluster_id"]))
        leads.append(event_start - int(selected["start_index"]))
    false_alarms = [
        signal for signal in signal_clusters if int(signal["cluster_id"]) not in matched_signals
    ]
    return {
        "event_clusters": len(event_clusters),
        "matched_event_clusters": len(leads),
        "missed_event_clusters": len(misses),
        "missed_event_sessions": int(sum(int(item["sessions"]) for item in misses)),
        "signal_clusters": len(signal_clusters),
        "false_alarm_clusters": len(false_alarms),
        "false_alarm_clusters_per_true_event": (
            float(len(false_alarms) / len(event_clusters)) if event_clusters else None
        ),
        "median_warning_lead_sessions": float(np.median(leads)) if leads else None,
        "median_detection_delay_sessions": float(np.median([-value for value in leads]))
        if leads
        else None,
        "lead_samples": leads,
    }


def _forward_max(series: pd.Series, horizon: int) -> pd.Series:
    return pd.Series(
        [
            pd.to_numeric(series.iloc[index + 1 : index + horizon + 1], errors="coerce").max()
            if index + horizon < len(series)
            else np.nan
            for index in range(len(series))
        ],
        index=series.index,
    )


def _forward_mean(series: pd.Series, horizon: int) -> pd.Series:
    return pd.Series(
        [
            pd.to_numeric(series.iloc[index + 1 : index + horizon + 1], errors="coerce").mean()
            if index + horizon < len(series)
            else np.nan
            for index in range(len(series))
        ],
        index=series.index,
    )


def _timing_audit(ledger: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    result = ledger.copy()
    development_change = pd.to_numeric(
        result.loc[result["session_date"].le(DEVELOPMENT_END), "d1_log_vix"], errors="coerce"
    ).dropna()
    acute_change_threshold = float(development_change.quantile(0.90))
    front_confirmations = (
        result["near_stress_log_ratio"].gt(0).astype(int)
        + result["f1_settle"].gt(result["f2_settle"]).astype(int)
        + result["d1_log_vix"].ge(acute_change_threshold).astype(int)
    )
    raw_predicates = {
        "acute_front_pressure": front_confirmations.ge(2),
        "front_inversion": result["f1_settle"].gt(result["f2_settle"]),
        "mid_curve_diffusion": result["stress_tenor_scope_candidate"].eq("BROAD")
        & result["mid_curve_pressure_state_candidate"].eq("RISING"),
        "broad_stress": result["stress_tenor_scope_candidate"].eq("BROAD")
        & result["mid_curve_pressure_state_candidate"].isin(["RISING", "PRICED"]),
        "mid_pressure_receding": result["mid_curve_pressure_state_candidate"].eq("RECEDING"),
        "carry_recovered": result["carry_environment_state_candidate"].eq("OPEN"),
    }
    raw_predicates["broad_stress"] = (
        raw_predicates["broad_stress"].rolling(5, min_periods=5).sum().ge(3)
    )
    signal_predicates = {
        "acute_front_pressure": result["hard_acute"].eq(True),
        "front_inversion": result["carry_answer"].eq("INVERTED"),
        "mid_curve_diffusion": result["persistence_answer"].eq("DIFFUSING"),
        "broad_stress": result["persistence_answer"].eq("PERSISTENT"),
        "mid_pressure_receding": result["repair_answer"].eq("CONFIRMED"),
        "carry_recovered": result["data_status"].eq("OK")
        & result["carry_answer"].eq("SUPPORTIVE")
        & result["shock_answer"].eq("CALM")
        & result["persistence_answer"].eq("NORMAL"),
    }
    result["v1_short_allowed_fact"] = signal_predicates["carry_recovered"]

    all_clusters: dict[str, list[dict[str, Any]]] = {}
    signal_clusters: dict[str, list[dict[str, Any]]] = {}
    for name, predicate in raw_predicates.items():
        result, all_clusters[name] = _mark_clusters(result, name, predicate)
        signal_clusters[name] = _true_clusters(result["session_date"], signal_predicates[name])

    follow_through = {
        "acute_front_pressure": (_forward_max(result["d1_log_vix"], 5), 1),
        "front_inversion": (result["front_slope30"], -1),
        "mid_curve_diffusion": (result["fwd5_log_f4_f7_level"], 1),
        "broad_stress": (result["fwd10_log_f4_f7_level"], 1),
        "mid_pressure_receding": (result["fwd5_log_f4_f7_level"], -1),
        "carry_recovered": (_forward_mean(result["carry_open_day_candidate"], 5), 1),
    }
    metrics: dict[str, Any] = {}
    for name, clusters in all_clusters.items():
        matched = _match_clusters(
            clusters,
            signal_clusters[name],
            lead_window=5 if name not in {"broad_stress", "carry_recovered"} else 10,
            lag_window=5 if name not in {"broad_stress", "carry_recovered"} else 10,
        )
        series, expected_sign = follow_through[name]
        values = [float(series.iloc[int(cluster["start_index"])]) for cluster in clusters]
        metrics[name] = {
            **matched,
            "event_cluster_sessions": [
                {
                    key: value
                    for key, value in cluster.items()
                    if key not in {"start_index", "end_index"}
                }
                for cluster in clusters
            ],
            "leave_one_event_cluster_out_direction": _loco_direction(values, expected_sign),
        }

    repair_signals = signal_clusters["mid_pressure_receding"]
    premature = sum(
        bool(raw_predicates["broad_stress"].iloc[int(cluster["start_index"])])
        and not bool(raw_predicates["mid_pressure_receding"].iloc[int(cluster["start_index"])])
        for cluster in repair_signals
    )
    recovery_delays: list[int] = []
    short_allowed = signal_predicates["carry_recovered"].to_numpy(dtype=bool)
    for cluster in all_clusters["carry_recovered"]:
        start = int(cluster["start_index"])
        end = int(cluster["end_index"])
        offsets = np.flatnonzero(short_allowed[start : end + 1])
        recovery_delays.append(int(offsets[0]) if len(offsets) else end - start + 1)
    timing_summary = {
        "event_ledger_definition": {
            "acute_d1_log_vix_development_p90": acute_change_threshold,
            "source": "raw price and F1-F7 curve facts; no phase used as a label",
        },
        "events": metrics,
        "repair_confirmation": {
            "signal_clusters": len(repair_signals),
            "premature_release_clusters": int(premature),
            "premature_release_rate": float(premature / len(repair_signals))
            if repair_signals
            else None,
        },
        "carry_recovery": {
            "raw_recovery_clusters": len(recovery_delays),
            "median_sessions_still_closed_after_recovery": float(np.median(recovery_delays))
            if recovery_delays
            else None,
            "max_sessions_still_closed_after_recovery": int(max(recovery_delays))
            if recovery_delays
            else None,
        },
    }
    return result, timing_summary


def _reliability_bins(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    bins = pd.cut(
        frame["calibrated_probability"],
        bins=np.linspace(0.0, 1.0, 11),
        include_lowest=True,
    )
    records = []
    for interval, group in frame.groupby(bins, observed=True):
        records.append(
            {
                "bin": str(interval),
                "n": int(len(group)),
                "mean_probability": float(group["calibrated_probability"].mean()),
                "event_rate": float(group["label"].mean()),
            }
        )
    return records


def _simple_probability_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    complete = frame.dropna(subset=["label", "calibrated_probability", "base_rate_at_prediction"])
    if complete.empty:
        return {"samples": 0}
    model = brier_score(complete["label"].to_numpy(), complete["calibrated_probability"].to_numpy())
    base = brier_score(complete["label"].to_numpy(), complete["base_rate_at_prediction"].to_numpy())
    return {
        "samples": int(len(complete)),
        "positives": int(complete["label"].sum()),
        "brier_model": model,
        "brier_base": base,
        "brier_skill": float(1.0 - model / base) if base > 0 else None,
        "calibration_gap": float(
            abs(complete["calibrated_probability"].mean() - complete["label"].mean())
        ),
    }


def _candidate_event_summary(
    ledger: pd.DataFrame,
    *,
    onset: pd.Series,
    predicate: pd.Series,
    horizon: int,
    minimum_true: int = 1,
) -> dict[str, Any]:
    onset_known = onset.notna() & onset.eq(True)
    labels = pd.Series(np.nan, index=ledger.index, dtype=float)
    for index in ledger.index[onset_known]:
        end = int(index) + horizon
        if end >= len(ledger):
            continue
        future = predicate.iloc[int(index) + 1 : end + 1]
        if len(future) != horizon or future.isna().any():
            continue
        labels.loc[index] = float(future.astype(bool).sum() >= minimum_true)

    def cohort(mask: pd.Series) -> dict[str, Any]:
        eligible = onset_known & mask
        completed = eligible & labels.notna()
        positive = completed & labels.eq(1)
        negative = completed & labels.eq(0)
        return {
            "eligible": int(eligible.sum()),
            "completed": int(completed.sum()),
            "positive": int(positive.sum()),
            "negative": int(negative.sum()),
            "base_rate": float(labels.loc[completed].mean()) if completed.any() else None,
            "positive_clusters": int((positive & ~positive.shift(1, fill_value=False)).sum()),
            "model_sample_gate": bool(
                completed.sum() >= 252 and positive.sum() >= 30 and negative.sum() >= 30
            ),
        }

    return {
        "horizon_sessions": horizon,
        "overall": cohort(pd.Series(True, index=ledger.index)),
        "development": cohort(ledger["session_date"].le(DEVELOPMENT_END)),
        "confirmation": cohort(ledger["session_date"].ge(CONFIRMATION_START)),
    }


def _probability_audit(
    ledger: pd.DataFrame, targets: pd.DataFrame, oof: pd.DataFrame
) -> dict[str, Any]:
    latest = pd.Timestamp(ledger["session_date"].max()).normalize()
    events, metadata, _, _ = run_probability_job(
        ledger,
        prediction_date=latest,
        target_ledger=targets,
        oof_ledger=oof,
    )
    existing: dict[str, Any] = {}
    stress_mask = (
        ledger[["acute_front_pressure__event", "broad_stress__event"]].fillna(False).any(axis=1)
    )
    stress_dates = set(ledger.loc[stress_mask, "session_date"])
    for event in EVENT_ORDER:
        event_targets = targets.loc[targets["event_id"].eq(event)].copy()
        completed_targets = event_targets.loc[
            event_targets["label_status"].isin(["OBSERVED_0", "OBSERVED_1"])
        ]
        event_oof = oof.loc[oof["event_id"].eq(event)].copy()
        completed_oof = event_oof.loc[
            event_oof["label_status"].isin(["OBSERVED_0", "OBSERVED_1"])
            & event_oof["calibrated_probability"].notna()
            & event_oof["base_rate_at_prediction"].notna()
            & pd.to_datetime(event_oof["outcome_available_at"], utc=True).le(
                pd.Timestamp(decision_as_of(latest)).tz_convert("UTC")
            )
            & pd.to_datetime(event_oof["prediction_date"]).lt(latest)
        ].sort_values("prediction_date")
        annual = {
            str(year): _simple_probability_metrics(frame)
            for year, frame in completed_oof.groupby(
                pd.to_datetime(completed_oof["prediction_date"]).dt.year
            )
        }
        event_oof_dates = pd.to_datetime(completed_oof["prediction_date"]).dt.normalize()
        crisis = completed_oof.loc[event_oof_dates.isin(stress_dates)]
        non_crisis = completed_oof.loc[~event_oof_dates.isin(stress_dates)]
        existing[event] = {
            "event_status_counts": {
                str(key): int(value)
                for key, value in event_targets["event_status"].value_counts().items()
            },
            "label_status_counts": {
                str(key): int(value)
                for key, value in event_targets["label_status"].value_counts().items()
            },
            "completed_samples": int(len(completed_targets)),
            "positive_samples": int(completed_targets["label"].sum()),
            "raw_oof": int(len(event_oof)),
            "calibrated_oof": int(event_oof["calibrated_probability"].notna().sum()),
            "latest_252_acceptance": acceptance_metrics(completed_oof),
            "latest_publication": events[event],
            "publication_fallback_reason": metadata[event].get("fallback_reason"),
            "annual": annual,
            "crisis_strata": {
                "raw_stress_sessions": _simple_probability_metrics(crisis),
                "other_sessions": _simple_probability_metrics(non_crisis),
            },
            "reliability": _reliability_bins(completed_oof),
        }

    training_prediction = pd.to_datetime(oof["training_latest_prediction_date"])
    prediction = pd.to_datetime(oof["prediction_date"])
    purge_cutoff = prediction.map(lambda value: add_sessions(value, -20))
    training_outcome = pd.to_datetime(oof["training_latest_outcome_available_at"], utc=True)
    prediction_as_of = prediction.map(
        lambda value: pd.Timestamp(decision_as_of(value)).tz_convert("UTC")
    )
    integrity = {
        "duplicate_oof_keys": int(oof.duplicated(["event_id", "prediction_date"]).sum()),
        "purge_boundary_violations": int(training_prediction.gt(purge_cutoff).sum()),
        "outcome_availability_violations": int(training_outcome.gt(prediction_as_of).sum()),
        "calibration_without_convergence": int(
            (oof["calibrated_probability"].notna() & ~oof["calibration_converged"].eq(True)).sum()
        ),
    }

    known_mid = ledger["mid_curve_pressure_state_candidate"].ne("UNKNOWN")
    known_scope = ledger["stress_tenor_scope_candidate"].ne("UNKNOWN")
    diffusion_onset = ledger["stress_tenor_scope_candidate"].eq("FRONT").where(known_scope)
    diffusion_predicate = (
        ledger["stress_tenor_scope_candidate"].eq("BROAD")
        & ledger["mid_curve_pressure_state_candidate"].isin(["RISING", "PRICED"])
    ).where(known_scope & known_mid)
    broad_onset = diffusion_predicate.copy()
    accelerate_onset = (
        ~ledger["mid_curve_pressure_state_candidate"].isin(["RISING", "PRICED"])
    ).where(known_mid)
    accelerate_predicate = (
        ledger["mid_curve_pressure_state_candidate"].eq("RISING").where(known_mid)
    )
    recovery_onset = (
        ledger["carry_environment_state_candidate"].isin(["CLOSED", "RECOVERING"])
        & (
            ledger["front_pressure_raw"].eq(True)
            | ledger["mid_curve_pressure_state_candidate"].ne("QUIET")
        )
    ).where(ledger["carry_environment_state_candidate"].ne("UNKNOWN"))
    recovery_predicate = (
        ledger["carry_environment_state_candidate"]
        .eq("OPEN")
        .where(ledger["carry_environment_state_candidate"].ne("UNKNOWN"))
    )
    candidates = {
        "front_stress_diffuses_to_mid_curve_10d": _candidate_event_summary(
            ledger, onset=diffusion_onset, predicate=diffusion_predicate, horizon=10
        ),
        "broad_stress_persists_10d": _candidate_event_summary(
            ledger, onset=broad_onset, predicate=diffusion_predicate, horizon=10, minimum_true=5
        ),
        "mid_curve_pressure_accelerates_5d": _candidate_event_summary(
            ledger, onset=accelerate_onset, predicate=accelerate_predicate, horizon=5
        ),
        "carry_environment_recovers_10d": _candidate_event_summary(
            ledger, onset=recovery_onset, predicate=recovery_predicate, horizon=10
        ),
    }
    return {"integrity": integrity, "existing_events": existing, "candidate_events": candidates}


def _series_equal(left: pd.Series, right: pd.Series) -> bool:
    if len(left) != len(right):
        return False
    for left_value, right_value in zip(left, right, strict=True):
        if isinstance(left_value, (list, tuple, np.ndarray)) or isinstance(
            right_value, (list, tuple, np.ndarray)
        ):
            if _as_list(left_value) != _as_list(right_value):
                return False
            continue
        if pd.isna(left_value) and pd.isna(right_value):
            continue
        if isinstance(left_value, (float, np.floating)) or isinstance(
            right_value, (float, np.floating)
        ):
            if not np.isclose(float(left_value), float(right_value), rtol=1e-12, atol=1e-12):
                return False
            continue
        if left_value != right_value:
            return False
    return True


def _append_invariance(
    observations: pd.DataFrame,
    vx_contracts: pd.DataFrame,
    full_features: pd.DataFrame,
    full_states: pd.DataFrame,
    full_oof: pd.DataFrame,
) -> dict[str, Any]:
    observation_dates = pd.to_datetime(observations["session_date"]).dt.normalize()
    vx_dates = pd.to_datetime(vx_contracts["session_date"]).dt.normalize()
    prefix_features, prefix_states = build_state_history(
        observations.loc[observation_dates.le(APPEND_INVARIANCE_CUTOFF)].copy(),
        vx_contracts.loc[vx_dates.le(APPEND_INVARIANCE_CUTOFF)].copy(),
    )
    expected_features = full_features.loc[
        pd.to_datetime(full_features["session_date"]).dt.normalize().le(APPEND_INVARIANCE_CUTOFF)
    ].reset_index(drop=True)
    expected_states = full_states.loc[
        pd.to_datetime(full_states["session_date"]).dt.normalize().le(APPEND_INVARIANCE_CUTOFF)
    ].reset_index(drop=True)
    changed_features = [
        column
        for column in expected_features.columns
        if not _series_equal(expected_features[column], prefix_features[column])
    ]
    changed_states = [
        column
        for column in expected_states.columns
        if not _series_equal(expected_states[column], prefix_states[column])
    ]
    _, prefix_oof = prepare_probability_artifacts(prefix_states)
    comparison_columns = [
        "decision_score",
        "base_probability",
        "base_rate_at_prediction",
        "training_latest_prediction_date",
        "training_latest_outcome_available_at",
        "base_rate_samples",
        "base_rate_positive",
        "base_rate_negative",
        "training_samples",
        "training_positive",
        "training_negative",
        "converged",
        "iterations",
        "calibrated_probability",
        "platt_a",
        "platt_b",
        "calibration_samples",
        "calibration_converged",
    ]
    common = prefix_oof.merge(
        full_oof,
        on=["event_id", "prediction_date"],
        how="inner",
        suffixes=("_prefix", "_full"),
        validate="one_to_one",
    )
    changed_oof = [
        column
        for column in comparison_columns
        if not _series_equal(common[f"{column}_prefix"], common[f"{column}_full"])
    ]
    return {
        "cutoff": APPEND_INVARIANCE_CUTOFF.date().isoformat(),
        "prefix_state_rows": int(len(prefix_states)),
        "common_oof_rows": int(len(common)),
        "changed_feature_columns": changed_features,
        "changed_state_columns": changed_states,
        "changed_oof_columns": changed_oof,
        "passed": not changed_features and not changed_states and not changed_oof,
    }


def _pseudo_gap_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    actual_gap = frame.loc[frame["strict_vxcm30"].isna() & frame["f1_days"].gt(30)]
    max_overshoot = float(actual_gap["f1_days"].sub(30).max())
    pseudo = frame.loc[
        frame["pseudo_gap_vxcm30"].notna() & frame["f2_days"].sub(30).between(0, max_overshoot)
    ].copy()
    pseudo["error"] = pseudo["pseudo_gap_vxcm30"] - pseudo["strict_vxcm30"]
    pseudo["absolute_error"] = pseudo["error"].abs()
    pseudo["absolute_percentage_error"] = pseudo["absolute_error"] / pseudo["strict_vxcm30"]

    def metrics(group: pd.DataFrame) -> dict[str, Any]:
        if group.empty:
            return {"samples": 0}
        return {
            "samples": int(len(group)),
            "bias_vix_points": float(group["error"].mean()),
            "mae_vix_points": float(group["absolute_error"].mean()),
            "median_absolute_percentage_error": float(group["absolute_percentage_error"].median()),
            "p95_absolute_percentage_error": float(
                group["absolute_percentage_error"].quantile(0.95)
            ),
            "max_absolute_percentage_error": float(group["absolute_percentage_error"].max()),
            "correlation": float(group[["strict_vxcm30", "pseudo_gap_vxcm30"]].corr().iloc[0, 1]),
        }

    return {
        "actual_gap_max_days_beyond_30": max_overshoot,
        "overall": metrics(pseudo),
        "development": metrics(pseudo.loc[pseudo["session_date"].le(DEVELOPMENT_END)]),
        "confirmation": metrics(pseudo.loc[pseudo["session_date"].ge(CONFIRMATION_START)]),
    }


def _data_summary(
    ledger: pd.DataFrame,
    observation_summary: dict[str, Any],
    vx_contracts: pd.DataFrame,
    append_invariance: dict[str, Any],
) -> dict[str, Any]:
    raw_vx = vx_contracts.copy()
    raw_vx["settle"] = pd.to_numeric(raw_vx["settle"], errors="coerce")
    direct_gap = ledger["strict_vxcm30"].isna()
    propagated_gap = ledger["d5_log_vxcm30"].isna()
    ok = ledger["data_status"].eq("OK")
    ok_required = [
        "formal_vintage_eligible",
        "carry_risk_score",
        "shock_score",
        "tail_price_score",
        "persistence_score",
        "repair_score",
        "baseline_score",
        "carry_answer",
        "shock_answer",
        "tail_answer",
        "persistence_answer",
        "repair_answer",
        "phase",
    ]
    ok_violations = int(
        ledger.loc[ok, ok_required].isna().any(axis=1).sum()
        + ledger.loc[
            ok, [column for column in ok_required if column.endswith("answer") or column == "phase"]
        ]
        .eq("UNKNOWN")
        .any(axis=1)
        .sum()
    )
    selection_mismatch = 0
    formula_mismatch = 0
    for row in ledger.itertuples(index=False):
        if [str(value) for value in _as_list(row.vx_contract_ids)] != [
            str(value) for value in _as_list(row.f1_f7_contract_ids)[:6]
        ]:
            selection_mismatch += 1
        left = _finite(row.vxcm30)
        right = _finite(row.strict_vxcm30)
        if (left is None) != (right is None) or (
            left is not None and right is not None and not np.isclose(left, right, atol=1e-12)
        ):
            formula_mismatch += 1
    tri_unknown = ledger.loc[ok & ledger["recent_stress"].isna()]
    return {
        "observations": observation_summary,
        "vx_contracts": {
            "rows": int(len(raw_vx)),
            "sessions": int(pd.to_datetime(raw_vx["session_date"]).nunique()),
            "contracts": int(raw_vx["contract_id"].nunique()),
            "duplicate_revision_keys": int(
                raw_vx.duplicated(["contract_id", "session_date", "revision_id"]).sum()
            ),
            "nonpositive_settlements": int(raw_vx["settle"].le(0).sum()),
            "vintages": sorted(set(raw_vx["vintage_kind"].astype(str))),
            "methodologies": sorted(set(raw_vx["methodology_version"].astype(str))),
        },
        "f1_f7": {
            "sessions": int(len(ledger)),
            "complete_sessions": int(ledger["f1_f7_count"].eq(7).sum()),
            "sequential_sessions": int(ledger["f1_f7_sequential"].eq(True).sum()),
            "v1_selection_mismatches": selection_mismatch,
        },
        "vxcm30": {
            "direct_unavailable_sessions": int(direct_gap.sum()),
            "all_direct_gaps_have_f1_beyond_30": bool(
                ledger.loc[direct_gap, "f1_days"].gt(30).all()
            ),
            "gap_origin": "FORMULA_DOMAIN_NO_LEFT_BRACKET",
            "bounded_candidate_available": int(
                ledger.loc[direct_gap, "bounded_vxcm30_candidate"].notna().sum()
            ),
            "v1_formula_mismatches": formula_mismatch,
            "d5_propagated_unavailable_sessions": int(propagated_gap.sum()),
            "additional_d5_propagation_sessions": int((propagated_gap & ~direct_gap).sum()),
            "pseudo_gap_validation": _pseudo_gap_metrics(ledger),
        },
        "data_status": {
            "counts": {
                str(key): int(value) for key, value in ledger["data_status"].value_counts().items()
            },
            "ok_required_field_violations": ok_violations,
            "ok_rows_with_recent_stress_unknown": int(len(tri_unknown)),
            "final_repair_answers_when_recent_stress_unknown": {
                str(key): int(value)
                for key, value in tri_unknown["repair_answer"].value_counts().items()
            },
            "tri_state_ownership": (
                "An unknown hidden recent_stress is permitted on an OK current row only when "
                "three-valued logic still determines the published repair answer."
            ),
        },
        "future_append_invariance": append_invariance,
    }


def _tenor_and_state_summary(ledger: pd.DataFrame) -> tuple[dict[str, Any], dict[str, Any]]:
    tenor = {
        "candidate_formulas": {
            "f4_f7_level": "mean(F4,F5,F6,F7), VIX points",
            "f4_f7_slope30": "ln(F7/F4)*30/(D7-D4)",
            "f4_f7_inversion_share": "(I(F4>F5)+I(F5>F6)+I(F6>F7))/3",
            "front_to_mid_log_ratio": "ln(mean(F4:F7)/mean(F1:F2))",
            "changes": "5/10-session level, normalized slope and inversion-share changes",
        },
        "candidate_state_counts": {
            "mid_curve_pressure_state": {
                str(key): int(value)
                for key, value in ledger["mid_curve_pressure_state_candidate"]
                .value_counts()
                .items()
            },
            "stress_tenor_scope": {
                str(key): int(value)
                for key, value in ledger["stress_tenor_scope_candidate"].value_counts().items()
            },
            "tenor_stage": {
                str(key): int(value)
                for key, value in ledger["tenor_stage_candidate"].value_counts().items()
            },
        },
        "conditional_weather_by_persistence_answer": _conditional_weather(
            ledger, "persistence_answer"
        ),
        "conditional_weather_by_phase": _conditional_weather(ledger, "phase"),
    }
    repair = ledger.loc[ledger["repair_answer"].eq("CONFIRMED")]
    pressure = ledger.loc[ledger["phase"].eq("PRESSURE_BUILDING")]
    state = {
        "persistence_answer_vs_direct_tenor_stage": _cross_tab(
            ledger, "persistence_answer", "tenor_stage_candidate"
        ),
        "phase_vs_direct_tenor_stage": _cross_tab(ledger, "phase", "tenor_stage_candidate"),
        "pressure_building_stage_counts": {
            str(key): int(value)
            for key, value in pressure["tenor_stage_candidate"].value_counts().items()
        },
        "repair_confirmed": {
            "sessions": int(len(repair)),
            "carry_environment_open_sessions": int(
                repair["carry_environment_state_candidate"].eq("OPEN").sum()
            ),
            "carry_environment_open_rate": float(
                repair["carry_environment_state_candidate"].eq("OPEN").mean()
            )
            if len(repair)
            else None,
            "front_slope_positive_rate": float(repair["front_slope30"].gt(0).mean())
            if len(repair)
            else None,
            "basis_positive_rate": float(repair["basis30_audit_candidate"].gt(0).mean())
            if len(repair)
            else None,
            "mid_slope_positive_rate": float(repair["f4_f7_slope30"].gt(0).mean())
            if len(repair)
            else None,
        },
        "ok_answer_unknown_counts": {
            column: int(ledger.loc[ledger["data_status"].eq("OK"), column].eq("UNKNOWN").sum())
            for column in [
                "carry_answer",
                "shock_answer",
                "tail_answer",
                "persistence_answer",
                "repair_answer",
                "phase",
            ]
        },
    }
    return tenor, state


def run_v2_business_audit(project_dir: str | Path) -> dict[str, Path]:
    """Run the Phase-A, weather-only MatVIX V1 business audit."""

    root = Path(project_dir).resolve()
    manifest, tables = _verify_frozen_baseline(root)
    observations = read_parquet(root / "data" / "raw" / "observations.parquet")
    vx_contracts = read_parquet(root / "data" / "raw" / "vx_contracts.parquet")
    features = tables["features"]
    states = tables["states"]
    targets = tables["targets"]
    oof = tables["oof"]
    for frame, column in ((features, "session_date"), (states, "session_date")):
        frame[column] = pd.to_datetime(frame[column]).dt.normalize()
    states = states.sort_values("session_date").reset_index(drop=True)

    curve = _build_curve_audit(vx_contracts, states["session_date"])
    ledger = states.merge(curve, on="session_date", how="left", validate="one_to_one")
    ledger, observation_summary = _add_observation_audit(ledger, observations)
    ledger["audit_window"] = _split_name(ledger["session_date"])
    ledger = _add_tenor_candidates(ledger)

    target_columns = ["event_id", "prediction_date", "event_status", "label", "label_status"]
    for event in EVENT_ORDER:
        event_targets = targets.loc[targets["event_id"].eq(event), target_columns].rename(
            columns={
                "prediction_date": "session_date",
                "event_status": f"{event}__event_status",
                "label": f"{event}__label",
                "label_status": f"{event}__label_status",
            }
        )
        ledger = ledger.merge(
            event_targets.drop(columns="event_id"),
            on="session_date",
            how="left",
            validate="one_to_one",
        )
    ledger, timing_summary = _timing_audit(ledger)

    append_invariance = _append_invariance(observations, vx_contracts, features, states, oof)
    data_summary = _data_summary(ledger, observation_summary, vx_contracts, append_invariance)
    tenor_summary, state_summary = _tenor_and_state_summary(ledger)
    probability_summary = _probability_audit(ledger, targets, oof)

    summary: dict[str, Any] = {
        "audit_version": AUDIT_VERSION,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "contract": "MATVIX_V2_CONSTRUCTION_PLAN.md v1.0",
        "baseline": {
            "code_sha": manifest.get("code_sha"),
            "manifest_sha256": _sha256(root / "outputs" / "v2_baseline" / "v1_manifest.json"),
            "sessions": int(len(ledger)),
            "first_session": _date_text(ledger["session_date"].min()),
            "last_session": _date_text(ledger["session_date"].max()),
        },
        "evidence_boundary": {
            "weather_inputs_only": True,
            "product_prices_read": False,
            "strategy_or_pnl_built": False,
            "html_generated": False,
            "quarantine_read": False,
            "historical_pit_boundary": sorted(set(states["pit_evidence"].dropna().astype(str))),
        },
        "data": data_summary,
        "tenor": tenor_summary,
        "state": state_summary,
        "timing": timing_summary,
        "probability": probability_summary,
    }
    output_dir = root / "outputs" / "v2_audit"
    daily_path = write_parquet(ledger, output_dir / "business_audit_daily.parquet")
    summary_path = write_json(summary, output_dir / "business_audit_summary.json")
    return {"daily": daily_path, "summary": summary_path}
