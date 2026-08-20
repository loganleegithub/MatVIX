from __future__ import annotations

import numpy as np
import pandas as pd


def beta_smoothed_base_rate(
    labels: pd.Series | np.ndarray,
    *,
    max_samples: int = 756,
    minimum_samples: int = 252,
    alpha: float = 1.0,
    beta: float = 1.0,
) -> tuple[float | None, int, int, int]:
    values = pd.to_numeric(pd.Series(labels), errors="coerce").dropna().astype(int)
    values = values.iloc[-max_samples:]
    count = len(values)
    positives = int(values.sum())
    negatives = count - positives
    if count < minimum_samples:
        return None, count, positives, negatives
    rate = (positives + alpha) / (count + alpha + beta)
    return float(rate), count, positives, negatives


def historical_samples_available(
    target_ledger: pd.DataFrame,
    *,
    event: str,
    prediction_date: pd.Timestamp,
    decision_as_of: pd.Timestamp,
) -> pd.DataFrame:
    frame = target_ledger.loc[
        (target_ledger["event_id"] == event)
        & (pd.to_datetime(target_ledger["prediction_date"]) < prediction_date)
        & (target_ledger["label_status"].isin(["OBSERVED_0", "OBSERVED_1"]))
        & (
            pd.to_datetime(target_ledger["outcome_available_at"], utc=True)
            <= decision_as_of.tz_convert("UTC")
        )
    ].copy()
    return frame.sort_values("prediction_date")
