from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.special import expit, logit

CALIBRATION_CLIP_MIN = 1e-6
CALIBRATION_CLIP_MAX = 1.0 - 1e-6
INTERCEPT_SLOPE = 1.0
INTERCEPT_ROOT_LOWER = -40.0
INTERCEPT_ROOT_UPPER = 40.0


def binary_log_loss(y: np.ndarray, p: np.ndarray) -> float:
    clipped = np.clip(p, CALIBRATION_CLIP_MIN, CALIBRATION_CLIP_MAX)
    return float(-np.mean(y * np.log(clipped) + (1 - y) * np.log(1 - clipped)))


def fit_intercept(raw_probabilities: np.ndarray, labels: np.ndarray) -> float:
    probabilities = np.clip(
        np.asarray(raw_probabilities, dtype=float),
        CALIBRATION_CLIP_MIN,
        CALIBRATION_CLIP_MAX,
    )
    y = np.asarray(labels, dtype=float)
    if probabilities.ndim != 1 or y.ndim != 1 or len(probabilities) != len(y) or not len(y):
        raise ValueError("Rolling intercept requires equal non-empty one-dimensional inputs")
    z = logit(probabilities)

    def score(intercept: float) -> float:
        return float(np.mean(expit(z + intercept)) - np.mean(y))

    return float(brentq(score, INTERCEPT_ROOT_LOWER, INTERCEPT_ROOT_UPPER))


def apply_intercept(raw_probability: float, intercept: float) -> float:
    raw = float(np.clip(raw_probability, CALIBRATION_CLIP_MIN, CALIBRATION_CLIP_MAX))
    return float(
        np.clip(
            expit(INTERCEPT_SLOPE * logit(raw) + intercept),
            CALIBRATION_CLIP_MIN,
            CALIBRATION_CLIP_MAX,
        )
    )


def brier_score(labels: np.ndarray, probabilities: np.ndarray) -> float:
    y = np.asarray(labels, dtype=float)
    p = np.asarray(probabilities, dtype=float)
    return float(np.mean((p - y) ** 2))


def exact_ece_252(
    labels: np.ndarray,
    probabilities: np.ndarray,
    prediction_dates: np.ndarray,
) -> float:
    if len(labels) != 252:
        raise ValueError("Exact MatVIX ECE requires 252 samples")
    frame = pd.DataFrame(
        {
            "label": np.asarray(labels, dtype=float),
            "probability": np.asarray(probabilities, dtype=float),
            "prediction_date": pd.to_datetime(prediction_dates),
            "_order": np.arange(252),
        }
    ).sort_values(["probability", "prediction_date", "_order"], kind="mergesort")
    sizes = [51, 51, 50, 50, 50]
    cursor = 0
    ece = 0.0
    for size in sizes:
        bin_frame = frame.iloc[cursor : cursor + size]
        ece += (size / 252.0) * abs(
            float(bin_frame["probability"].mean()) - float(bin_frame["label"].mean())
        )
        cursor += size
    return float(ece)


def acceptance_metrics(completed_published: pd.DataFrame) -> dict[str, float | bool | int]:
    frame = completed_published.sort_values("prediction_date").tail(252)
    if len(frame) < 252:
        return {"accepted": False, "samples": len(frame)}
    positives = int(frame["label"].sum())
    negatives = len(frame) - positives
    if positives < 20 or negatives < 20:
        return {
            "accepted": False,
            "samples": len(frame),
            "positives": positives,
            "negatives": negatives,
        }
    model_brier = brier_score(frame["label"], frame["published_probability"])
    base_brier = brier_score(frame["label"], frame["base_rate_at_prediction"])
    skill = 1.0 - model_brier / base_brier if base_brier > 0 else float("-inf")
    ece = exact_ece_252(
        frame["label"].to_numpy(),
        frame["published_probability"].to_numpy(),
        frame["prediction_date"].to_numpy(),
    )
    return {
        "accepted": bool(skill >= 0.02 and ece <= 0.07),
        "samples": 252,
        "positives": positives,
        "negatives": negatives,
        "brier_model": model_brier,
        "brier_base": base_brier,
        "brier_skill": float(skill),
        "ece": ece,
    }
