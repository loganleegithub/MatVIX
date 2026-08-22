from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

CHICAGO = ZoneInfo("America/Chicago")
CURVE_CONTRACTS = 7
VXCM30_TARGET_DAYS = 30.0
VXCM30_MAX_FRONT_DAYS = 36.0
VXCM30_METHODOLOGY = "VXCM30_LINEAR_30D_V2"


def _to_chicago_timestamp(value: object) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize(CHICAGO)
    return ts.tz_convert(CHICAGO)


def select_standard_monthly_curve(
    contracts: pd.DataFrame,
    session_date: pd.Timestamp | str,
    *,
    count: int = CURVE_CONTRACTS,
) -> pd.DataFrame:
    session = pd.Timestamp(session_date).normalize()
    cutoff = pd.Timestamp(datetime.combine(session.date(), time(15, 0), tzinfo=CHICAGO))
    required = {"session_date", "settle", "final_settlement_timestamp", "contract_id"}
    if contracts.empty or not required.issubset(contracts.columns):
        return pd.DataFrame(columns=sorted(required))
    frame = contracts.copy()
    frame["session_date"] = pd.to_datetime(frame["session_date"]).dt.normalize()
    frame = frame.loc[frame["session_date"] == session]
    if "is_standard_monthly" in frame.columns:
        frame = frame.loc[frame["is_standard_monthly"].fillna(False)]
    frame = frame.dropna(subset=["settle", "final_settlement_timestamp"])
    frame["_final_ts"] = frame["final_settlement_timestamp"].map(_to_chicago_timestamp)
    frame = frame.loc[frame["_final_ts"] > cutoff]
    frame = frame.sort_values(["_final_ts", "contract_id"]).drop_duplicates(
        "_final_ts", keep="last"
    )
    return frame.head(count).reset_index(drop=True)


def _has_consecutive_contract_months(curve: pd.DataFrame) -> bool:
    if curve.empty:
        return False
    if {"contract_year", "contract_month"}.issubset(curve.columns):
        years = pd.to_numeric(curve["contract_year"], errors="coerce")
        months = pd.to_numeric(curve["contract_month"], errors="coerce")
        if years.isna().any() or months.isna().any():
            return False
        serial = (years.astype(int) * 12 + months.astype(int)).to_numpy()
    else:
        timestamps = (
            curve["_final_ts"]
            if "_final_ts" in curve
            else curve["final_settlement_timestamp"].map(_to_chicago_timestamp)
        )
        serial = np.array([timestamp.year * 12 + timestamp.month for timestamp in timestamps])
    return bool(len(serial) == CURVE_CONTRACTS and np.all(np.diff(serial) == 1))


def standard_monthly_curve_is_complete(curve: pd.DataFrame) -> bool:
    if len(curve) != CURVE_CONTRACTS or "settle" not in curve or "contract_id" not in curve:
        return False
    settlements = pd.to_numeric(curve["settle"], errors="coerce")
    identifiers = curve["contract_id"].astype(str)
    timestamps = (
        curve["_final_ts"]
        if "_final_ts" in curve
        else curve["final_settlement_timestamp"].map(_to_chicago_timestamp)
    )
    return bool(
        identifiers.nunique() == CURVE_CONTRACTS
        and settlements.notna().all()
        and settlements.gt(0).all()
        and all(left < right for left, right in zip(timestamps[:-1], timestamps[1:], strict=True))
        and _has_consecutive_contract_months(curve)
    )


def curve_features_for_session(
    contracts: pd.DataFrame, session_date: pd.Timestamp | str
) -> dict[str, object]:
    session = pd.Timestamp(session_date).normalize()
    curve = select_standard_monthly_curve(contracts, session, count=CURVE_CONTRACTS)
    output: dict[str, object] = {
        "session_date": session,
        "ts12": np.nan,
        "ts12_log_ratio": np.nan,
        "front_slope30": np.nan,
        "front_curve_level": np.nan,
        "f4_f7_level": np.nan,
        "f4_f7_slope30": np.nan,
        "f4_f7_inversion_share": np.nan,
        "front_to_mid_log_ratio": np.nan,
        "vxcm30": np.nan,
        "vxcm30_source_kind": "UNAVAILABLE",
        "vxcm30_methodology": None,
        "curve_inversion_share": np.nan,
        "vx_contract_ids": [],
        "vx_settles": [],
        "vx_days_to_final": [],
        "vxcm30_bracket_ids": [],
        "vx_revision_ids": [],
        "vx_vintage_kinds": [],
        "vx_formal_vintage_eligible": False,
        "vx_source_rows": 0,
    }
    if curve.empty:
        return output
    cutoff = pd.Timestamp(datetime.combine(session.date(), time(15, 0), tzinfo=CHICAGO))
    settlements = curve["settle"].astype(float).to_numpy()
    final_times = (
        curve["_final_ts"]
        if "_final_ts" in curve
        else curve["final_settlement_timestamp"].map(_to_chicago_timestamp)
    )
    days = np.array([(timestamp - cutoff).total_seconds() / 86400 for timestamp in final_times])
    ids = curve["contract_id"].astype(str).tolist()
    vintages = curve["vintage_kind"].astype(str).tolist() if "vintage_kind" in curve else []
    revisions = curve["revision_id"].astype(str).tolist() if "revision_id" in curve else []
    complete_curve = standard_monthly_curve_is_complete(curve) and bool(
        len(days) == CURVE_CONTRACTS
        and np.all(np.isfinite(days))
        and np.all(days > 0)
        and np.all(np.diff(days) > 0)
    )
    formal = (
        complete_curve
        and len(vintages) == CURVE_CONTRACTS
        and all(value in {"OBSERVED_PIT", "ASSUMED_PIT"} for value in vintages)
    )
    output.update(
        {
            "vx_contract_ids": ids,
            "vx_settles": settlements.tolist(),
            "vx_days_to_final": days.tolist(),
            "vx_revision_ids": revisions,
            "vx_vintage_kinds": vintages,
            "vx_formal_vintage_eligible": formal,
            "vx_source_rows": len(curve),
        }
    )
    if len(curve) >= 2 and settlements[0] > 0 and settlements[1] > 0 and days[1] > days[0]:
        ratio = settlements[1] / settlements[0]
        output["ts12"] = ratio - 1.0
        output["ts12_log_ratio"] = float(np.log(ratio))
        output["front_slope30"] = float(np.log(ratio) * 30.0 / (days[1] - days[0]))
    if formal:
        front_level = float(np.mean(settlements[:2]))
        mid_level = float(np.mean(settlements[3:7]))
        output["front_curve_level"] = front_level
        output["f4_f7_level"] = mid_level
        output["f4_f7_slope30"] = float(
            np.log(settlements[6] / settlements[3]) * 30.0 / (days[6] - days[3])
        )
        output["f4_f7_inversion_share"] = float(
            np.count_nonzero(settlements[3:6] > settlements[4:7]) / 3.0
        )
        output["front_to_mid_log_ratio"] = float(np.log(mid_level / front_level))
        for index in range(len(curve) - 1):
            left_days, right_days = days[index], days[index + 1]
            if left_days <= VXCM30_TARGET_DAYS < right_days:
                left_weight = (right_days - VXCM30_TARGET_DAYS) / (right_days - left_days)
                right_weight = (VXCM30_TARGET_DAYS - left_days) / (right_days - left_days)
                output["vxcm30"] = float(
                    left_weight * settlements[index] + right_weight * settlements[index + 1]
                )
                output["vxcm30_bracket_ids"] = [ids[index], ids[index + 1]]
                output["vxcm30_source_kind"] = "DIRECT_BRACKET_INTERPOLATION"
                output["vxcm30_methodology"] = VXCM30_METHODOLOGY
                break
        if (
            output["vxcm30_source_kind"] == "UNAVAILABLE"
            and VXCM30_TARGET_DAYS < days[0] <= VXCM30_MAX_FRONT_DAYS
        ):
            output["vxcm30"] = float(
                settlements[0]
                + (settlements[1] - settlements[0])
                * (VXCM30_TARGET_DAYS - days[0])
                / (days[1] - days[0])
            )
            output["vxcm30_bracket_ids"] = [ids[0], ids[1]]
            output["vxcm30_source_kind"] = "BOUNDED_BACKWARD_EXTRAPOLATION"
            output["vxcm30_methodology"] = VXCM30_METHODOLOGY
    if complete_curve:
        output["curve_inversion_share"] = float(
            np.count_nonzero(settlements[:5] > settlements[1:6]) / 5.0
        )
    return output


def build_futures_curve_table(
    contracts: pd.DataFrame, sessions: pd.Series | pd.DatetimeIndex
) -> pd.DataFrame:
    records = [curve_features_for_session(contracts, session) for session in sessions]
    return pd.DataFrame(records)
