from __future__ import annotations

import numpy as np
import pandas as pd


def ewma94_variance(
    spx_close: pd.Series,
    *,
    lambda_: float = 0.94,
    seed_returns: int = 252,
) -> tuple[pd.Series, pd.Series]:
    close = pd.to_numeric(spx_close, errors="coerce")
    adjacent = close.notna() & close.shift(1).notna()
    returns = pd.Series(np.nan, index=close.index, dtype=float)
    returns.loc[adjacent] = np.log(close.loc[adjacent] / close.shift(1).loc[adjacent])
    variance = pd.Series(np.nan, index=close.index, dtype=float)

    contiguous_count = 0
    seed_buffer: list[float] = []
    state: float | None = None
    seeded = False
    for pos in range(len(close)):
        value = returns.iloc[pos]
        if not seeded:
            if np.isfinite(value):
                contiguous_count += 1
                seed_buffer.append(float(value))
                if contiguous_count == seed_returns:
                    state = float(np.var(np.asarray(seed_buffer), ddof=1))
                    variance.iloc[pos] = state
                    seeded = True
            else:
                contiguous_count = 0
                seed_buffer = []
            continue
        if not np.isfinite(value):
            # Preserve the previous state internally but publish null on the gap and
            # on the first valid observation after the gap (where return is null).
            continue
        assert state is not None
        state = lambda_ * state + (1.0 - lambda_) * float(value) ** 2
        variance.iloc[pos] = state
    return returns, variance


def vrp_features(spx_close: pd.Series, vix_close: pd.Series) -> pd.DataFrame:
    returns, daily_variance = ewma94_variance(spx_close, lambda_=0.94, seed_returns=252)
    annual = 252.0 * daily_variance
    implied = (pd.to_numeric(vix_close, errors="coerce") / 100.0) ** 2
    vrp = implied - annual
    return pd.DataFrame(
        {
            "spx_log_return": returns,
            "ewma94_daily_variance": daily_variance,
            "rv_forecast_ewma94": annual,
            "vrp_ewma94": vrp,
        },
        index=spx_close.index,
    )
