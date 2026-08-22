from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from conftest import make_curve

from matvix.calendar import vix_final_settlement_date
from matvix.features.futures_curve import curve_features_for_session, select_standard_monthly_curve
from matvix.features.iv_curve import (
    forward_variance,
    forward_volatility,
    iv_curve_features,
    log_ratio,
    ratio,
)
from matvix.features.percentile import midrank_percentile, rolling_midrank_percentile
from matvix.features.technical import atr, macd, rsi, seeded_ema, stochastic, true_range
from matvix.features.vrp import ewma94_variance, vrp_features


def test_standard_monthly_f1_f2_excludes_expired_and_weekly(session: pd.Timestamp) -> None:
    curve = make_curve(session)
    expired = curve.iloc[[0]].copy()
    expired["contract_id"] = "EXPIRED"
    expired["final_settlement_timestamp"] = (
        pd.Timestamp(session.date()).tz_localize("America/Chicago") + pd.Timedelta(hours=8)
    ).isoformat()
    weekly = curve.iloc[[1]].copy()
    weekly["contract_id"] = "WEEKLY"
    weekly["is_standard_monthly"] = False
    selected = select_standard_monthly_curve(pd.concat([expired, weekly, curve]), session)
    assert selected["contract_id"].tolist() == [f"VX_TEST_{i}" for i in range(1, 8)]


def test_settlement_day_roll_excludes_contract_after_final_time(session: pd.Timestamp) -> None:
    curve = make_curve(session)
    curve.loc[0, "final_settlement_timestamp"] = (
        pd.Timestamp(session.date()).tz_localize("America/Chicago") + pd.Timedelta(hours=8)
    ).isoformat()
    selected = select_standard_monthly_curve(curve, session)
    assert selected.iloc[0]["contract_id"] == "VX_TEST_2"


def test_contango_and_backwardation_signs(session: pd.Timestamp) -> None:
    contango = curve_features_for_session(
        make_curve(session, settles=[18, 19, 20, 21, 22, 23, 24]), session
    )
    backward = curve_features_for_session(
        make_curve(session, settles=[20, 19, 18, 17, 16, 15, 14]), session
    )
    assert contango["ts12"] > 0 and contango["front_slope30"] > 0
    assert backward["ts12"] < 0 and backward["front_slope30"] < 0


def test_ts12_and_front_slope_golden(session: pd.Timestamp) -> None:
    output = curve_features_for_session(
        make_curve(
            session,
            settles=[20, 22, 23, 24, 25, 26, 27],
            days=[10, 40, 70, 100, 130, 160, 190],
        ),
        session,
    )
    assert output["ts12"] == pytest.approx(0.10)
    assert output["front_slope30"] == pytest.approx(math.log(1.1))


def test_true_30_day_bracket_can_be_f2_f3(session: pd.Timestamp) -> None:
    output = curve_features_for_session(
        make_curve(
            session,
            settles=[20, 21, 24, 25, 26, 27, 28, 29],
            days=[-1, 15, 45, 75, 105, 135, 165, 195],
        ),
        session,
    )
    # The first row is expired and removed; the 15/45 day pair are selected F1/F2 after filtering.
    assert output["vxcm30_bracket_ids"] == ["VX_TEST_2", "VX_TEST_3"]
    assert output["vxcm30"] == pytest.approx(22.5)


def test_no_extrapolation_without_30_day_bracket(session: pd.Timestamp) -> None:
    output = curve_features_for_session(
        make_curve(session, days=[40, 70, 100, 130, 160, 190, 220]), session
    )
    assert math.isnan(float(output["vxcm30"]))
    assert output["vxcm30_bracket_ids"] == []


def test_v2_curve_selects_f1_f7_and_labels_direct_vxcm30(session: pd.Timestamp) -> None:
    output = curve_features_for_session(
        make_curve(
            session,
            settles=[18, 19, 20, 21, 22, 23, 24],
            days=[10, 40, 70, 100, 130, 160, 190],
        ),
        session,
    )

    assert output["vx_contract_ids"] == [f"VX_TEST_{i}" for i in range(1, 8)]
    assert output["vxcm30"] == pytest.approx(18 + (19 - 18) * 20 / 30)
    assert output["vxcm30_source_kind"] == "DIRECT_BRACKET_INTERPOLATION"
    assert output["vxcm30_methodology"] == "VXCM30_LINEAR_30D_V2"


def test_v2_vxcm30_uses_bounded_backward_extrapolation(session: pd.Timestamp) -> None:
    output = curve_features_for_session(
        make_curve(
            session,
            settles=[19, 20, 21, 22, 23, 24, 25],
            days=[34, 64, 94, 124, 154, 184, 214],
        ),
        session,
    )

    assert output["vxcm30"] == pytest.approx(19 + (20 - 19) * (30 - 34) / (64 - 34))
    assert output["vxcm30_bracket_ids"] == ["VX_TEST_1", "VX_TEST_2"]
    assert output["vxcm30_source_kind"] == "BOUNDED_BACKWARD_EXTRAPOLATION"


@pytest.mark.parametrize(
    ("days", "vintage_kind"),
    [
        ([37, 67, 97, 127, 157, 187, 217], "ASSUMED_PIT"),
        ([34, 64, 94, 124, 154, 184, 214], "PROVIDER_BACKTESTED"),
    ],
)
def test_v2_vxcm30_refuses_out_of_bound_or_nonformal_reconstruction(
    session: pd.Timestamp, days: list[int], vintage_kind: str
) -> None:
    output = curve_features_for_session(
        make_curve(
            session,
            settles=[19, 20, 21, 22, 23, 24, 25],
            days=days,
            vintage_kind=vintage_kind,
        ),
        session,
    )

    assert math.isnan(float(output["vxcm30"]))
    assert output["vxcm30_bracket_ids"] == []
    assert output["vxcm30_source_kind"] == "UNAVAILABLE"
    assert output["vxcm30_methodology"] is None


def test_v2_curve_refuses_a_skipped_standard_month(session: pd.Timestamp) -> None:
    output = curve_features_for_session(
        make_curve(
            session,
            settles=[18, 19, 20, 21, 22, 23, 24],
            days=[10, 70, 100, 130, 160, 190, 220],
        ),
        session,
    )

    assert output["vx_formal_vintage_eligible"] is False
    assert math.isnan(float(output["vxcm30"]))
    assert output["vxcm30_source_kind"] == "UNAVAILABLE"


def test_legacy_curve_inversion_share_uses_first_six_but_requires_f1_f7(
    session: pd.Timestamp,
) -> None:
    full = curve_features_for_session(
        make_curve(session, settles=[20, 19, 21, 20, 22, 21, 23]), session
    )
    short = curve_features_for_session(make_curve(session).iloc[:6], session)
    assert full["curve_inversion_share"] == pytest.approx(3 / 5)
    assert math.isnan(float(short["curve_inversion_share"]))


def test_f4_f7_tenor_facts_have_frozen_units_and_direction(session: pd.Timestamp) -> None:
    output = curve_features_for_session(
        make_curve(
            session,
            settles=[20, 21, 22, 24, 23, 22, 21],
            days=[10, 40, 70, 100, 130, 160, 190],
        ),
        session,
    )

    assert output["front_curve_level"] == pytest.approx(20.5)
    assert output["f4_f7_level"] == pytest.approx(22.5)
    assert output["f4_f7_slope30"] == pytest.approx(math.log(21 / 24) * 30 / 90)
    assert output["f4_f7_inversion_share"] == 1.0
    assert output["front_to_mid_log_ratio"] == pytest.approx(math.log(22.5 / 20.5))


def test_ratio_crossings() -> None:
    assert ratio(20, 20) == 1.0
    assert log_ratio(20, 20) == 0.0
    assert ratio(21, 20) > 1.0
    assert log_ratio(19, 20) < 0.0
    assert math.isnan(ratio(1, 0))
    assert math.isnan(log_ratio(-1, 2))


def test_forward_variance_golden() -> None:
    iv_a, iv_b = 20.0, 25.0
    expected = ((93 / 365) * 0.25**2 - (30 / 365) * 0.20**2) / ((93 - 30) / 365)
    assert forward_variance(iv_a, 30, iv_b, 93) == pytest.approx(expected)
    assert forward_volatility(iv_a, 30, iv_b, 93) == pytest.approx(math.sqrt(expected) * 100)


def test_negative_forward_variance_is_preserved_but_forward_vol_is_unavailable() -> None:
    variance = forward_variance(50, 30, 10, 93)
    assert variance < 0
    assert math.isnan(forward_volatility(50, 30, 10, 93))
    features = iv_curve_features(vix9d=20, vix=50, vix3m=10, vix6m=12)
    assert features["fvar_30_93"] < 0
    assert math.isnan(features["fvol_30_93"])


def test_iv_curve_uses_target_indices_not_vx_months() -> None:
    result = iv_curve_features(vix9d=18, vix=20, vix3m=22, vix6m=24)
    assert result["ratio_9_30"] == pytest.approx(0.9)
    assert result["ratio_30_93"] == pytest.approx(20 / 22)
    assert result["near_stress_log_ratio"] == pytest.approx(math.log(0.9))


def test_midrank_percentile_ties() -> None:
    assert midrank_percentile(2, [1, 2, 2, 3]) == pytest.approx(0.5)


def test_rolling_percentile_excludes_current_and_does_not_scan_older() -> None:
    series = pd.Series([0.0, 100.0, np.nan, 2.0], name="x")
    result = rolling_midrank_percentile(series, reference_sessions=2, minimum_valid=2)
    assert math.isnan(result.iloc[3])  # fixed prior two sessions contain only one valid value
    series2 = pd.Series([1.0, 2.0, 3.0], name="x")
    result2 = rolling_midrank_percentile(series2, reference_sessions=2, minimum_valid=2)
    assert result2.iloc[2] == 1.0


def test_true_range_and_wilder_atr_golden() -> None:
    high = pd.Series([10, 12, 13, 14], dtype=float)
    low = pd.Series([8, 9, 10, 11], dtype=float)
    close = pd.Series([9, 11, 12, 13], dtype=float)
    tr = true_range(high, low, close)
    assert tr.tolist() == pytest.approx([2, 3, 3, 3])
    out = atr(high, low, close, period=3)
    assert out.iloc[2] == pytest.approx(8 / 3)
    assert out.iloc[3] == pytest.approx((2 * (8 / 3) + 3) / 3)


def test_seeded_ema_initialization_and_gap_reset() -> None:
    s = pd.Series([1, 2, 3, 4, np.nan, 10, 11, 12], dtype=float)
    out = seeded_ema(s, 3)
    assert out.iloc[2] == 2.0
    assert out.iloc[3] == 3.0
    assert math.isnan(out.iloc[5]) and math.isnan(out.iloc[6])
    assert out.iloc[7] == 11.0


def test_rsi_boundaries() -> None:
    rising = pd.Series(range(20), dtype=float)
    flat = pd.Series([5.0] * 20)
    falling = pd.Series(range(20, 0, -1), dtype=float)
    assert rsi(rising, 14).dropna().iloc[-1] == 100.0
    assert rsi(flat, 14).dropna().iloc[-1] == 50.0
    assert rsi(falling, 14).dropna().iloc[-1] == 0.0


def test_stochastic_zero_range_is_50() -> None:
    values = pd.Series([10.0] * 20)
    k, d = stochastic(values, values, values, period=14, d_period=3)
    assert k.iloc[13] == 50.0
    assert d.iloc[15] == 50.0


def test_macd_warmup_positions() -> None:
    close = pd.Series(np.arange(1, 50), dtype=float)
    line, signal, hist = macd(close)
    assert line.first_valid_index() == 25
    assert signal.first_valid_index() == 33
    assert hist.first_valid_index() == 33


def test_vrp_uses_only_past_and_current_return_not_future() -> None:
    close = pd.Series(100 * np.exp(np.arange(260) * 0.001), dtype=float)
    returns, variance = ewma94_variance(close, seed_returns=252)
    assert variance.first_valid_index() == 252
    before = variance.copy()
    changed = close.copy()
    changed.iloc[-1] *= 2
    _, changed_variance = ewma94_variance(changed, seed_returns=252)
    pd.testing.assert_series_equal(before.iloc[:-1], changed_variance.iloc[:-1])
    out = vrp_features(close, pd.Series([20.0] * len(close)))
    expected = 0.2**2 - 252 * variance.iloc[-1]
    assert out["vrp_ewma94"].iloc[-1] == pytest.approx(expected)


def test_vrp_gap_is_not_crossed() -> None:
    close = pd.Series(100 * np.exp(np.arange(260) * 0.001), dtype=float)
    close.iloc[254] = np.nan
    returns, variance = ewma94_variance(close, seed_returns=252)
    assert math.isnan(returns.iloc[254])
    assert math.isnan(returns.iloc[255])
    assert math.isnan(variance.iloc[254])
    assert math.isnan(variance.iloc[255])
    assert np.isfinite(variance.iloc[256])


def test_vix_final_settlement_holiday_rule() -> None:
    # April 2025 SPX standard expiry was Good Friday; VX Apr expiry moved to Apr 16.
    assert vix_final_settlement_date(2025, 4) == pd.Timestamp("2025-04-16").date()
