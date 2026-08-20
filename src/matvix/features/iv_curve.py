from __future__ import annotations

import math

import numpy as np


def ratio(a: float, b: float) -> float:
    if not np.isfinite(a) or not np.isfinite(b) or b == 0:
        return float("nan")
    return float(a / b)


def log_ratio(a: float, b: float) -> float:
    if not np.isfinite(a) or not np.isfinite(b) or a <= 0 or b <= 0:
        return float("nan")
    return float(math.log(a / b))


def forward_variance(iv_a: float, days_a: float, iv_b: float, days_b: float) -> float:
    if not np.isfinite(iv_a) or not np.isfinite(iv_b) or iv_a <= 0 or iv_b <= 0 or days_b <= days_a:
        return float("nan")
    time_a = days_a / 365.0
    time_b = days_b / 365.0
    q_a = (iv_a / 100.0) ** 2
    q_b = (iv_b / 100.0) ** 2
    # Preserve the annualized variance decomposition exactly, including a
    # negative value. A negative forward variance is economically invalid for
    # the downstream volatility calculation, but retaining it in the feature
    # table makes the data problem auditable instead of silently clipping or
    # deleting it.
    value = (time_b * q_b - time_a * q_a) / (time_b - time_a)
    return float(value)


def forward_volatility(iv_a: float, days_a: float, iv_b: float, days_b: float) -> float:
    variance = forward_variance(iv_a, days_a, iv_b, days_b)
    if not np.isfinite(variance) or variance < 0:
        return float("nan")
    return float(math.sqrt(variance) * 100.0)


def iv_curve_features(*, vix9d: float, vix: float, vix3m: float, vix6m: float) -> dict[str, float]:
    fvar_9_30 = forward_variance(vix9d, 9.0, vix, 30.0)
    fvar_30_93 = forward_variance(vix, 30.0, vix3m, 93.0)
    fvar_93_184 = forward_variance(vix3m, 93.0, vix6m, 184.0)
    return {
        "ratio_9_30": ratio(vix9d, vix),
        "near_stress_log_ratio": log_ratio(vix9d, vix),
        "ratio_30_93": ratio(vix, vix3m),
        "medium_front_log_ratio": log_ratio(vix, vix3m),
        "fvar_9_30": fvar_9_30,
        "fvar_30_93": fvar_30_93,
        "fvar_93_184": fvar_93_184,
        "fvol_9_30": math.sqrt(fvar_9_30) * 100
        if np.isfinite(fvar_9_30) and fvar_9_30 >= 0
        else np.nan,
        "fvol_30_93": math.sqrt(fvar_30_93) * 100
        if np.isfinite(fvar_30_93) and fvar_30_93 >= 0
        else np.nan,
        "fvol_93_184": math.sqrt(fvar_93_184) * 100
        if np.isfinite(fvar_93_184) and fvar_93_184 >= 0
        else np.nan,
    }
