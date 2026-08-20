from __future__ import annotations

import numpy as np
import pandas as pd


def midrank_percentile(value: float, reference: pd.Series | np.ndarray) -> float:
    if pd.isna(value):
        return float("nan")
    array = np.asarray(reference, dtype=float)
    array = array[np.isfinite(array)]
    if array.size == 0:
        return float("nan")
    below = np.count_nonzero(array < value)
    equal = np.count_nonzero(array == value)
    return float((below + 0.5 * equal) / array.size)


def rolling_midrank_percentile(
    series: pd.Series,
    *,
    reference_sessions: int = 756,
    minimum_valid: int = 504,
) -> pd.Series:
    """PIT percentile: prior sessions only, current observation excluded.

    The session window is fixed first, then invalid values are removed. The function
    never scans farther back to replace missing observations.
    """

    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    result = np.full(values.shape, np.nan, dtype=float)
    for index, value in enumerate(values):
        if not np.isfinite(value):
            continue
        start = max(0, index - reference_sessions)
        fixed_window = values[start:index]
        valid = fixed_window[np.isfinite(fixed_window)]
        if valid.size < minimum_valid:
            continue
        below = np.count_nonzero(valid < value)
        equal = np.count_nonzero(valid == value)
        result[index] = (below + 0.5 * equal) / valid.size
    return pd.Series(result, index=series.index, name=f"p_{series.name}")
