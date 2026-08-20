from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit


def binary_log_loss(y: np.ndarray, p: np.ndarray) -> float:
    clipped = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(clipped) + (1 - y) * np.log(1 - clipped)))


def fit_platt(
    decision_scores: np.ndarray,
    labels: np.ndarray,
    *,
    regularization: float = 1e-6,
) -> tuple[float, float, bool]:
    z = np.asarray(decision_scores, dtype=float)
    y = np.asarray(labels, dtype=float)

    def objective(params: np.ndarray) -> tuple[float, np.ndarray]:
        a, b = params
        logits = a * z + b
        probabilities = expit(logits)
        # Stable, unclipped Bernoulli negative log-likelihood.  Clipping is only
        # applied to the published probability, exactly as the v1 contract states.
        loss = float(np.mean(np.logaddexp(0.0, logits) - y * logits)) + regularization * (
            a * a + b * b
        )
        gradient_a = float(np.mean((probabilities - y) * z) + 2 * regularization * a)
        gradient_b = float(np.mean(probabilities - y) + 2 * regularization * b)
        return loss, np.asarray([gradient_a, gradient_b])

    result = minimize(
        lambda params: objective(params)[0],
        x0=np.asarray([1.0, 0.0]),
        jac=lambda params: objective(params)[1],
        method="L-BFGS-B",
        options={"maxiter": 1000, "ftol": 1e-12, "gtol": 1e-8},
    )
    return float(result.x[0]), float(result.x[1]), bool(result.success)


def apply_platt(decision_score: float, a: float, b: float) -> float:
    return float(np.clip(expit(a * decision_score + b), 1e-6, 1 - 1e-6))


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


def acceptance_metrics(completed_calibrated: pd.DataFrame) -> dict[str, float | bool | int]:
    frame = completed_calibrated.sort_values("prediction_date").tail(252)
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
    model_brier = brier_score(frame["label"], frame["calibrated_probability"])
    base_brier = brier_score(frame["label"], frame["base_rate_at_prediction"])
    skill = 1.0 - model_brier / base_brier if base_brier > 0 else float("-inf")
    ece = exact_ece_252(
        frame["label"].to_numpy(),
        frame["calibrated_probability"].to_numpy(),
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
