from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from matvix.calendar import sessions_in_range
from matvix.constants import FORMAL_VINTAGES
from matvix.data.point_in_time import pit_evidence_for_vintage, weakest_vintage
from matvix.features.futures_curve import build_futures_curve_table
from matvix.features.iv_curve import iv_curve_features
from matvix.features.technical import technical_features
from matvix.features.vrp import vrp_features


def _log_change(series: pd.Series, periods: int) -> pd.Series:
    current = pd.to_numeric(series, errors="coerce")
    previous = current.shift(periods)
    result = np.log(current / previous)
    result.loc[current.le(0) | previous.le(0)] = np.nan
    return result


def _level_change(series: pd.Series, periods: int) -> pd.Series:
    current = pd.to_numeric(series, errors="coerce")
    return current - current.shift(periods)


def _curve_methodology_signatures(vx_contracts: pd.DataFrame, curve: pd.DataFrame) -> pd.Series:
    signatures = pd.Series(None, index=curve.index, dtype=object)
    required = {"session_date", "contract_id", "methodology_version"}
    if vx_contracts.empty or not required.issubset(vx_contracts.columns):
        return signatures
    source = vx_contracts.copy()
    source["session_date"] = pd.to_datetime(source["session_date"]).dt.normalize()
    if "available_at" in source.columns:
        source["_available_sort"] = pd.to_datetime(source["available_at"], utc=True)
        source = source.sort_values("_available_sort", kind="stable")
    source = source.drop_duplicates(["session_date", "contract_id"], keep="last")
    daily = source.groupby("session_date")["methodology_version"].agg(
        lambda values: (
            "VX_SETTLE=" + ",".join(sorted({str(value) for value in values.dropna()}))
            if values.notna().any()
            else None
        )
    )
    sessions = pd.DatetimeIndex(pd.to_datetime(curve["session_date"])).normalize()
    signatures.loc[:] = daily.reindex(sessions).ffill().to_numpy(dtype=object)
    return signatures


def _combined_methodology_signature(raw: object, vx: object) -> str | None:
    if not isinstance(raw, str) or not raw or not isinstance(vx, str) or not vx:
        return None
    return f"{raw}|{vx}"


def _combined_vintage(raw: object, vx: object) -> str | None:
    kinds: list[str] = []
    valid_kinds = {"OBSERVED_PIT", "ASSUMED_PIT", "PROVIDER_BACKTESTED"}
    if isinstance(raw, str) and raw in valid_kinds:
        kinds.append(raw)
    if isinstance(vx, list):
        kinds.extend(str(value) for value in vx if str(value) in valid_kinds)
    return weakest_vintage(kinds)


def _front_curve_is_formal(row: pd.Series) -> bool:
    vintages = row.get("vx_vintage_kinds")
    front_slope = row.get("front_slope30")
    return bool(
        isinstance(vintages, list)
        and len(vintages) >= 2
        and all(str(value) in FORMAL_VINTAGES for value in vintages[:2])
        and front_slope is not None
        and pd.notna(front_slope)
    )


def _regime_groups(signatures: pd.Series) -> Iterable[pd.Index]:
    effective = signatures.ffill()
    valid = effective.notna()
    boundaries = effective.ne(effective.shift()) & valid
    regime_ids = boundaries.cumsum()
    for _, indices in effective.loc[valid].groupby(regime_ids.loc[valid]).groups.items():
        yield pd.Index(indices)


def _add_regime_bound_features(frame: pd.DataFrame) -> pd.DataFrame:
    technical = technical_features(frame)
    technical.loc[:, :] = np.nan
    vrp = vrp_features(frame["spx_close"], frame["vix_close"])
    vrp.loc[:, :] = np.nan
    change_columns = {
        "d1_log_vix": ("log", "vix_close", 1),
        "d5_log_vix": ("log", "vix_close", 5),
        "d5_log_vvix": ("log", "vvix_close", 5),
        "d5_log_vxcm30": ("log", "vxcm30", 5),
        "d5_front_slope30": ("level", "front_slope30", 5),
        "d5_basis30_eod": ("level", "basis30_eod", 5),
        "d5_near_stress_log_ratio": ("level", "near_stress_log_ratio", 5),
        "d5_skew": ("level", "skew_close", 5),
        "d5_fvol_30_93": ("level", "fvol_30_93", 5),
        "d5_fvol_93_184": ("level", "fvol_93_184", 5),
        "d5_log_f4_f7_level": ("log", "f4_f7_level", 5),
        "d5_f4_f7_slope30": ("level", "f4_f7_slope30", 5),
        "d5_f4_f7_inversion_share": ("level", "f4_f7_inversion_share", 5),
        "d10_log_f4_f7_level": ("log", "f4_f7_level", 10),
        "d10_f4_f7_slope30": ("level", "f4_f7_slope30", 10),
        "d10_f4_f7_inversion_share": ("level", "f4_f7_inversion_share", 10),
    }
    changes = pd.DataFrame(np.nan, index=frame.index, columns=change_columns, dtype=float)

    for indices in _regime_groups(frame["feature_methodology_signature"]):
        segment = frame.loc[indices]
        segment_technical = technical_features(segment)
        segment_vrp = vrp_features(segment["spx_close"], segment["vix_close"])
        technical.loc[indices, :] = segment_technical
        vrp.loc[indices, :] = segment_vrp
        for output, (kind, source, periods) in change_columns.items():
            if kind == "log":
                changes.loc[indices, output] = _log_change(segment[source], periods)
            else:
                changes.loc[indices, output] = _level_change(segment[source], periods)

    result = pd.concat([frame, technical, vrp, changes], axis=1)
    result["d5_near_stress"] = result["d5_near_stress_log_ratio"]
    return result


def _add_feature_lineage(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    current_vintage = result.apply(
        lambda row: _combined_vintage(row.get("raw_vintage_kind"), row.get("vx_vintage_kinds")),
        axis=1,
    )
    result["feature_vintage_kind"] = current_vintage.astype(object)
    for indices in _regime_groups(result["feature_methodology_signature"]):
        running: str | None = None
        for index in indices:
            value = current_vintage.loc[index]
            running = weakest_vintage(
                candidate for candidate in (running, value) if candidate is not None
            )
            result.loc[index, "feature_vintage_kind"] = running

    raw_formal = result["raw_formal_vintage_eligible"].fillna(False)
    vx_formal = result["vx_formal_vintage_eligible"].fillna(False)
    methodology_known = result["feature_methodology_signature"].notna()
    lineage_formal = result["feature_vintage_kind"].isin(FORMAL_VINTAGES)
    result["formal_vintage_eligible"] = raw_formal & vx_formal & methodology_known & lineage_formal
    result["pit_evidence"] = result["feature_vintage_kind"].map(pit_evidence_for_vintage)
    return result


def build_feature_table(
    raw_wide: pd.DataFrame,
    vx_contracts: pd.DataFrame,
    vintage_summary: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if raw_wide.empty:
        raise ValueError("raw_wide is empty")
    source = raw_wide.copy()
    source["session_date"] = pd.to_datetime(source["session_date"]).dt.normalize()
    source = source.sort_values("session_date").drop_duplicates("session_date", keep="last")
    official_sessions = sessions_in_range(
        source["session_date"].min().date(), source["session_date"].max().date()
    )
    source = (
        source.set_index("session_date")
        .reindex(official_sessions)
        .rename_axis("session_date")
        .reset_index()
    )

    curve = build_futures_curve_table(vx_contracts, source["session_date"])
    curve["vx_methodology_signature"] = _curve_methodology_signatures(vx_contracts, curve)
    frame = source.merge(curve, on="session_date", how="left")
    iv_records = [
        iv_curve_features(
            vix9d=row.vix9d_close,
            vix=row.vix_close,
            vix3m=row.vix3m_close,
            vix6m=row.vix6m_close,
        )
        for row in frame.itertuples(index=False)
    ]
    frame = pd.concat([frame.reset_index(drop=True), pd.DataFrame(iv_records)], axis=1)
    frame["basis30_eod"] = frame["vxcm30"] / frame["vix_close"] - 1.0

    if vintage_summary is not None and not vintage_summary.empty:
        summary = vintage_summary.copy()
        summary["session_date"] = pd.to_datetime(summary["session_date"]).dt.normalize()
        frame = frame.merge(summary, on="session_date", how="left")
    else:
        frame["source_rows"] = 0
        frame["raw_core_complete"] = False
        frame["raw_formal_vintage_eligible"] = False
        frame["raw_vintage_kind"] = None
        frame["raw_methodology_signature"] = None
    if "raw_methodology_signature" not in frame:
        frame["raw_methodology_signature"] = None
    frame["feature_methodology_signature"] = frame.apply(
        lambda row: _combined_methodology_signature(
            row.get("raw_methodology_signature"), row.get("vx_methodology_signature")
        ),
        axis=1,
    )
    frame["front_curve_formal_vintage_eligible"] = frame.apply(_front_curve_is_formal, axis=1)

    frame = _add_regime_bound_features(frame)
    frame["source_rows"] = (
        frame["source_rows"].fillna(0) + frame["vx_source_rows"].fillna(0)
    ).astype(int)
    return _add_feature_lineage(frame)
