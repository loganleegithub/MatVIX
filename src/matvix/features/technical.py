from __future__ import annotations

import numpy as np
import pandas as pd


def _contiguous_segments(series: pd.Series) -> list[pd.Index]:
    valid = series.notna()
    groups = valid.ne(valid.shift(fill_value=False)).cumsum()
    return [index for _, index in series[valid].groupby(groups[valid]).groups.items()]


def seeded_ema(series: pd.Series, period: int) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    output = pd.Series(np.nan, index=values.index, dtype=float)
    alpha = 2.0 / (period + 1.0)
    for segment_index in _contiguous_segments(values):
        segment = values.loc[segment_index]
        if len(segment) < period:
            continue
        seed_pos = period - 1
        seed = float(segment.iloc[:period].mean())
        output.loc[segment.index[seed_pos]] = seed
        previous = seed
        for position in range(period, len(segment)):
            previous = alpha * float(segment.iloc[position]) + (1.0 - alpha) * previous
            output.loc[segment.index[position]] = previous
    return output


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    high = pd.to_numeric(high, errors="coerce")
    low = pd.to_numeric(low, errors="coerce")
    close = pd.to_numeric(close, errors="coerce")
    previous_close = close.shift(1)
    components = pd.concat(
        [(high - low).abs(), (high - previous_close).abs(), (low - previous_close).abs()],
        axis=1,
    )
    result = components.max(axis=1, skipna=True)
    result.loc[high.isna() | low.isna() | close.isna()] = np.nan
    return result


def wilder_average(series: pd.Series, period: int) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    output = pd.Series(np.nan, index=values.index, dtype=float)
    for segment_index in _contiguous_segments(values):
        segment = values.loc[segment_index]
        if len(segment) < period:
            continue
        seed_pos = period - 1
        previous = float(segment.iloc[:period].mean())
        output.loc[segment.index[seed_pos]] = previous
        for position in range(period, len(segment)):
            previous = ((period - 1.0) * previous + float(segment.iloc[position])) / period
            output.loc[segment.index[position]] = previous
    return output


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    return wilder_average(true_range(high, low, close), period)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    close = pd.to_numeric(close, errors="coerce")
    delta = close.diff()
    delta.loc[close.isna() | close.shift(1).isna()] = np.nan
    gains = delta.clip(lower=0)
    losses = (-delta).clip(lower=0)
    avg_gain = wilder_average(gains, period)
    avg_loss = wilder_average(losses, period)
    output = pd.Series(np.nan, index=close.index, dtype=float)
    both_zero = avg_gain.eq(0) & avg_loss.eq(0)
    no_loss = avg_loss.eq(0) & avg_gain.gt(0)
    normal = avg_loss.gt(0)
    output.loc[both_zero] = 50.0
    output.loc[no_loss] = 100.0
    rs = avg_gain.loc[normal] / avg_loss.loc[normal]
    output.loc[normal] = 100.0 - 100.0 / (1.0 + rs)
    return output


def stochastic(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14, d_period: int = 3
) -> tuple[pd.Series, pd.Series]:
    highest = pd.to_numeric(high, errors="coerce").rolling(period, min_periods=period).max()
    lowest = pd.to_numeric(low, errors="coerce").rolling(period, min_periods=period).min()
    close = pd.to_numeric(close, errors="coerce")
    span = highest - lowest
    k = 100.0 * (close - lowest) / span
    k.loc[span.eq(0) & span.notna()] = 50.0
    d = k.rolling(d_period, min_periods=d_period).mean()
    return k, d


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal_period: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    fast_ema = seeded_ema(close, fast)
    slow_ema = seeded_ema(close, slow)
    line = fast_ema - slow_ema
    signal = seeded_ema(line, signal_period)
    histogram = line - signal
    return line, signal, histogram


def technical_features(frame: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame(index=frame.index)
    close = frame["vix_close"]
    result["vix_atr14"] = atr(frame["vix_high"], frame["vix_low"], close, 14)
    result["vix_atrp14"] = result["vix_atr14"] / close
    result["vix_ema5"] = seeded_ema(close, 5)
    result["vix_ema20"] = seeded_ema(close, 20)
    result["vix_ema5_minus_20"] = result["vix_ema5"] / result["vix_ema20"] - 1.0
    osc = (close - result["vix_ema20"]) / result["vix_atr14"]
    osc.loc[result["vix_atr14"].eq(0)] = 0.0
    result["cash_vix_oscillator"] = osc
    result["vix_rsi14"] = rsi(close, 14)
    result["vix_stochastic_k14"], result["vix_stochastic_d3"] = stochastic(
        frame["vix_high"], frame["vix_low"], close, 14, 3
    )
    (
        result["vix_macd_12_26"],
        result["vix_macd_signal_9"],
        result["vix_macd_histogram"],
    ) = macd(close, 12, 26, 9)
    return result
