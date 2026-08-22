from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from matvix.calendar import decision_as_of, observed_at_eod, sessions_in_range
from matvix.constants import LOGISTIC_FEATURES
from matvix.source_identity import OFFICIAL_OBSERVATION_IDENTITIES, VX_SETTLE_IDENTITY


@pytest.fixture
def session() -> pd.Timestamp:
    return pd.Timestamp("2025-01-02")


def make_curve(
    session_date: str | pd.Timestamp = "2025-01-02",
    *,
    settles: Iterable[float] = (18, 19, 20, 21, 22, 23, 24),
    days: Iterable[float] = (10, 40, 70, 100, 130, 160, 190),
    vintage_kind: str = "ASSUMED_PIT",
) -> pd.DataFrame:
    session = pd.Timestamp(session_date).normalize()
    settles = list(settles)
    days = list(days)
    cutoff = pd.Timestamp(session.date()).tz_localize("America/Chicago") + pd.Timedelta(hours=15)
    rows = []
    for index, (settle, day) in enumerate(zip(settles, days, strict=True), 1):
        final = cutoff + pd.Timedelta(days=float(day))
        rows.append(
            {
                "session_date": session,
                "contract_id": f"VX_TEST_{index}",
                "contract_year": final.year,
                "contract_month": final.month,
                "final_settlement_date": final.tz_localize(None).normalize(),
                "final_settlement_timestamp": final.isoformat(),
                "settle": float(settle),
                "series_id": "VX_SETTLE",
                "value": float(settle),
                "unit": "vix_points",
                "source": VX_SETTLE_IDENTITY.source,
                "source_symbol": VX_SETTLE_IDENTITY.source_symbol,
                "observed_at": observed_at_eod(session).isoformat(),
                "available_at": decision_as_of(session).isoformat(),
                "ingested_at": datetime.now(UTC).isoformat(),
                "revision_id": f"r{index}",
                "methodology_version": "TEST_V1",
                "vintage_kind": vintage_kind,
                "is_standard_monthly": True,
            }
        )
    return pd.DataFrame(rows)


def make_observations(
    start: str = "2024-01-02",
    end: str = "2025-06-30",
    *,
    vintage_kind: str = "ASSUMED_PIT",
) -> pd.DataFrame:
    sessions = sessions_in_range(start, end)
    rows: list[dict[str, object]] = []
    series = [
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
    ]
    for i, day in enumerate(sessions):
        vix = 18.0 + 2.0 * np.sin(i / 19.0) + 0.004 * i
        values = {
            "VIX_OPEN": vix * 0.99,
            "VIX_HIGH": vix * 1.04,
            "VIX_LOW": vix * 0.96,
            "VIX_CLOSE": vix,
            "VIX9D_CLOSE": vix * (0.92 + 0.04 * np.sin(i / 11.0)),
            "VIX3M_CLOSE": vix * (1.10 + 0.02 * np.cos(i / 17.0)),
            "VIX6M_CLOSE": vix * (1.18 + 0.02 * np.cos(i / 23.0)),
            "VVIX_CLOSE": 88.0 + 9.0 * np.sin(i / 13.0),
            "SKEW_CLOSE": 135.0 + 7.0 * np.cos(i / 29.0),
            "SPX_CLOSE": 4500.0 * np.exp(0.00025 * i + 0.006 * np.sin(i / 9.0)),
        }
        for name in series:
            identity = OFFICIAL_OBSERVATION_IDENTITIES[name]
            rows.append(
                {
                    "series_id": name,
                    "session_date": day,
                    "value": float(values[name]),
                    "unit": "index_points",
                    "source": identity.source,
                    "source_symbol": identity.source_symbol,
                    "observed_at": observed_at_eod(day).isoformat(),
                    "available_at": decision_as_of(day).isoformat(),
                    "ingested_at": "2026-01-01T00:00:00+00:00",
                    "revision_id": f"{name}-{day.date()}",
                    "methodology_version": "TEST_V1",
                    "vintage_kind": vintage_kind,
                }
            )
    return pd.DataFrame(rows)


def make_vx_history(sessions: Iterable[pd.Timestamp]) -> pd.DataFrame:
    frames = []
    for i, day in enumerate(sessions):
        level = 18.5 + 1.8 * np.sin(i / 19.0) + 0.003 * i
        settles = [level + 0.5 * j for j in range(7)]
        frames.append(make_curve(day, settles=settles))
    return pd.concat(frames, ignore_index=True)


def base_state_frame(n: int = 40) -> pd.DataFrame:
    sessions = sessions_in_range("2024-01-02", "2025-12-31")[:n]
    frame = pd.DataFrame({"session_date": sessions})
    frame["data_status"] = "OK"
    frame["formal_vintage_eligible"] = True
    frame["carry_risk_score"] = 40.0
    frame["shock_score"] = 35.0
    frame["tail_price_score"] = 50.0
    frame["persistence_score"] = 40.0
    frame["repair_score"] = 30.0
    frame["baseline_score"] = 41.0
    frame["d5_baseline_score"] = 0.0
    frame["front_slope30"] = 0.03
    frame["basis30_eod"] = 0.05
    frame["d5_front_slope30"] = 0.0
    frame["near_stress_log_ratio"] = -0.05
    frame["d1_log_vix"] = 0.0
    frame["d5_log_vix"] = 0.0
    frame["d5_log_vvix"] = 0.0
    frame["vvix_close"] = 90.0
    frame["skew_close"] = 135.0
    frame["d5_skew"] = 0.0
    frame["fvol_30_93"] = 20.0
    frame["fvol_93_184"] = 21.0
    frame["d5_fvol_30_93"] = 0.0
    frame["curve_inversion_share"] = 0.0
    frame["front_curve_level"] = 20.5
    frame["f4_f7_level"] = 22.5
    frame["f4_f7_slope30"] = 0.02
    frame["f4_f7_inversion_share"] = 0.0
    frame["front_to_mid_log_ratio"] = float(np.log(22.5 / 20.5))
    frame["d5_log_f4_f7_level"] = 0.0
    frame["d5_f4_f7_slope30"] = 0.0
    frame["d5_f4_f7_inversion_share"] = 0.0
    frame["d10_log_f4_f7_level"] = 0.0
    frame["d10_f4_f7_slope30"] = 0.0
    frame["d10_f4_f7_inversion_share"] = 0.0
    frame["d5_near_stress"] = 0.0
    frame["p_d5_fvol_30_93"] = 0.5
    frame["p_fvol_93_184"] = 0.5
    frame["p_neg_front_slope30"] = 0.4
    frame["p_neg_d5_front_slope30"] = 0.5
    frame["p_neg_basis30_eod"] = 0.35
    frame["p_near_stress"] = 0.3
    frame["p_d1_log_vix"] = 0.5
    frame["p_d5_log_vix"] = 0.5
    frame["p_d5_log_vvix"] = 0.5
    frame["p_vvix"] = 0.5
    frame["p_skew"] = 0.5
    frame["p_d5_skew"] = 0.5
    frame["p_fvol_30_93"] = 0.5
    frame["p_neg_d5_log_vix"] = 0.5
    frame["p_neg_d5_near_stress"] = 0.5
    frame["p_d5_front_slope30"] = 0.5
    frame["p_neg_d5_log_vvix"] = 0.5
    frame["p_neg_d5_fvol_30_93"] = 0.5
    frame["p_f4_f7_level"] = 0.5
    frame["p_neg_f4_f7_slope30"] = 0.5
    frame["p_d5_log_f4_f7_level"] = 0.5
    frame["p_neg_d5_log_f4_f7_level"] = 0.5
    frame["p_d5_f4_f7_slope30"] = 0.5
    frame["p_neg_d5_f4_f7_slope30"] = 0.5
    frame["p_cash_vix_oscillator"] = 0.5
    frame["front_confirmation_count"] = 0.0
    frame["hard_acute"] = False
    frame["persistent_day"] = False
    frame["persistent_now"] = False
    frame["recent_stress"] = False
    frame["repair_confirmed"] = False
    frame["front_pressure"] = False
    frame["stress_tenor_scope"] = "NONE"
    frame["mid_curve_pressure_state"] = "QUIET"
    frame["carry_open_day"] = False
    frame["carry_environment_state"] = "RECOVERING"
    frame["broad_pressure_day"] = False
    frame["broad_pressure_now"] = False
    frame["mid_curve_formal_vintage_eligible"] = True
    frame["broad_pressure_day_formal_vintage_eligible"] = True
    frame["carry_environment_formal_vintage_eligible"] = True
    frame["carry_answer"] = "MIXED"
    frame["shock_answer"] = "CALM"
    frame["tail_answer"] = "NORMAL"
    frame["persistence_answer"] = "NORMAL"
    frame["repair_answer"] = "INACTIVE"
    frame["raw_phase"] = "MIXED_TRANSITION"
    frame["phase"] = "MIXED_TRANSITION"
    frame["pressure_level"] = "WATCH"
    frame["direction"] = "STABLE"
    frame["carry_risk_scaled"] = 0.4
    frame["shock_scaled"] = 0.35
    frame["tail_price_scaled"] = 0.5
    frame["persistence_scaled"] = 0.4
    frame["repair_scaled"] = 0.3
    frame["score_change5_scaled"] = 0.5
    frame["inverse_score_change5_scaled"] = 0.5
    frame["front_confirmation_scaled"] = 0.0
    # Guarantee every fixed predictor exists.
    for features in LOGISTIC_FEATURES.values():
        for feature in features:
            if feature not in frame:
                frame[feature] = 0.5
    return frame


@pytest.fixture
def state_frame() -> pd.DataFrame:
    return base_state_frame()
