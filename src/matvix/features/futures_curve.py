from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

CHICAGO = ZoneInfo("America/Chicago")


def _to_chicago_timestamp(value: object) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize(CHICAGO)
    return ts.tz_convert(CHICAGO)


def select_standard_monthly_curve(
    contracts: pd.DataFrame,
    session_date: pd.Timestamp | str,
    *,
    count: int = 6,
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


def curve_features_for_session(
    contracts: pd.DataFrame, session_date: pd.Timestamp | str
) -> dict[str, object]:
    session = pd.Timestamp(session_date).normalize()
    curve = select_standard_monthly_curve(contracts, session, count=6)
    output: dict[str, object] = {
        "session_date": session,
        "ts12": np.nan,
        "ts12_log_ratio": np.nan,
        "front_slope30": np.nan,
        "vxcm30": np.nan,
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
    formal = (
        len(curve) == 6
        and len(vintages) == 6
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
    for index in range(len(curve) - 1):
        left_days, right_days = days[index], days[index + 1]
        if left_days <= 30.0 < right_days and right_days > left_days:
            left_weight = (right_days - 30.0) / (right_days - left_days)
            right_weight = (30.0 - left_days) / (right_days - left_days)
            output["vxcm30"] = float(
                left_weight * settlements[index] + right_weight * settlements[index + 1]
            )
            output["vxcm30_bracket_ids"] = [ids[index], ids[index + 1]]
            break
    if len(curve) == 6:
        output["curve_inversion_share"] = float(
            np.count_nonzero(settlements[:-1] > settlements[1:]) / 5.0
        )
    return output


def build_futures_curve_table(
    contracts: pd.DataFrame, sessions: pd.Series | pd.DatetimeIndex
) -> pd.DataFrame:
    records = [curve_features_for_session(contracts, session) for session in sessions]
    return pd.DataFrame(records)
