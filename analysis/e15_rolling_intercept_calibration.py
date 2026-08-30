from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import logit
from sklearn.linear_model import LogisticRegression

from matvix.probability.calibration import (  # type: ignore[import-untyped]
    apply_intercept,
    binary_log_loss,
    fit_intercept,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_OOF = Path("outputs/e15_h3_q1m/oof_ledger.parquet")
RECENT_OOF = Path("outputs/e15_h3_q1m/recent_oof_ledger.parquet")
OUTPUT_DIR = Path("outputs/e15_rolling_intercept_calibration")
LEDGER_OUTPUT = OUTPUT_DIR / "oof_ledger.parquet"
EVIDENCE_OUTPUT = OUTPUT_DIR / "evidence.json"
REPORT_OUTPUT = OUTPUT_DIR / "report.md"

CONTRACT_ID = "E15_H3_CAUSAL_ROLLING_INTERCEPT_001"
FROZEN_SHA256 = {
    HISTORICAL_OOF: "107d5bc0ff372fd6748bfcb54d3614a361b91ae21323329e7ad21c093785b775",
    RECENT_OOF: "5bc27eac3be0b4e27ef29c128f5f63eac698845fddcc95b689b53d3186b0e136",
}

CALIBRATION_MAX = 252
CALIBRATION_MIN_POSITIVE = 20
CALIBRATION_MIN_NEGATIVE = 20
PROBABILITY_CLIP = 1e-6
BOOTSTRAP_SEED = 15_015
BOOTSTRAP_BLOCKS = (20, 84)
BOOTSTRAP_BATCH = 250
DEFAULT_DRAWS = 5_000
CALIBRATION_ODDS_LOWER = math.log(0.80)
CALIBRATION_ODDS_UPPER = math.log(1.25)
CALIBRATION_SLOPE_LOWER = 0.75
CALIBRATION_SLOPE_UPPER = 1.25
CALIBRATION_WRMS_MAX = 0.05
REGIME_GAP_MAX = 0.025
BIN_MIN_ORIGINS = 50
BIN_MIN_EPISODES = 10
PROBABILITY_BINS = (
    0.0,
    0.025,
    0.075,
    0.125,
    0.20,
    0.30,
    0.40,
    0.60,
    1.000001,
)


class ResearchError(RuntimeError):
    pass


def _rooted(root: Path, relative: Path) -> Path:
    return root / relative


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def load_frozen_inputs(root: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    identities: dict[str, Any] = {}
    frames: list[pd.DataFrame] = []
    for relative, expected in FROZEN_SHA256.items():
        path = _rooted(root, relative)
        if not path.exists():
            raise ResearchError(f"Frozen input is missing: {path}")
        actual = _sha256(path)
        identities[str(relative)] = {"expected_sha256": expected, "actual_sha256": actual}
        if actual != expected:
            raise ResearchError(f"Frozen input identity changed: {relative}: {actual}")
        frames.append(pd.read_parquet(path))

    panel = pd.concat(frames, ignore_index=True).sort_values("origin_session", kind="stable")
    panel = panel.reset_index(drop=True)
    required = {
        "origin_session",
        "forecast_as_of",
        "outcome_available_at",
        "label",
        "label_status",
        "evaluation_cohort",
        "episode_id",
        "b0_probability",
        "b1_probability",
        "b1_genuine",
        "h3_probability",
        "h3_genuine",
        "h3_state",
    }
    missing = sorted(required.difference(panel.columns))
    if missing:
        raise ResearchError(f"Frozen H3 inputs lack columns: {missing}")
    panel["origin_session"] = pd.to_datetime(panel["origin_session"]).dt.normalize()
    panel["forecast_as_of"] = pd.to_datetime(panel["forecast_as_of"], utc=True)
    panel["outcome_available_at"] = pd.to_datetime(panel["outcome_available_at"], utc=True)
    if panel.empty or panel["origin_session"].duplicated().any():
        raise ResearchError("Frozen H3 inputs are empty or contain duplicate origins")
    if not panel["label_status"].eq("OBSERVED").all():
        raise ResearchError("Frozen H3 inputs contain outcomes outside OBSERVED state")
    labels = pd.to_numeric(panel["label"], errors="coerce")
    if not labels.isin([0, 1]).all():
        raise ResearchError("Frozen H3 labels are not binary")
    for column in ("b0_probability", "b1_probability", "h3_probability"):
        values = pd.to_numeric(panel[column], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(values).all() or ((values < 0.0) | (values > 1.0)).any():
            raise ResearchError(f"Frozen H3 input has invalid probabilities: {column}")
    return panel, identities


def completed_calibration_training(panel: pd.DataFrame, current: pd.Series) -> pd.DataFrame:
    origin = pd.Timestamp(current["origin_session"])
    as_of = pd.Timestamp(current["forecast_as_of"])
    mask = (
        panel["origin_session"].lt(origin)
        & panel["outcome_available_at"].le(as_of)
        & panel["label_status"].eq("OBSERVED")
        & panel["h3_genuine"].astype(bool)
    )
    return panel.loc[mask].sort_values("origin_session", kind="stable").tail(CALIBRATION_MAX)


def build_rolling_intercept_ledger(panel: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for _, current in panel.iterrows():
        training = completed_calibration_training(panel, current)
        positives = int(training["label"].sum()) if not training.empty else 0
        negatives = len(training) - positives
        ready = (
            len(training) <= CALIBRATION_MAX
            and positives >= CALIBRATION_MIN_POSITIVE
            and negatives >= CALIBRATION_MIN_NEGATIVE
        )
        h3_genuine = bool(current["h3_genuine"])
        h3_probability = float(current["h3_probability"])
        intercept = math.nan
        probability = h3_probability
        if not h3_genuine:
            state = "ABSTAIN_H3"
            genuine = False
        elif not ready:
            state = "IDENTITY_WARMUP"
            genuine = False
        else:
            intercept = fit_intercept(
                training["h3_probability"].to_numpy(dtype=float),
                training["label"].to_numpy(dtype=float),
            )
            probability = apply_intercept(h3_probability, intercept)
            state = "RI_EMITTED"
            genuine = True

        records.append(
            {
                "origin_session": pd.Timestamp(current["origin_session"]),
                "forecast_as_of": pd.Timestamp(current["forecast_as_of"]),
                "outcome_available_at": pd.Timestamp(current["outcome_available_at"]),
                "evaluation_cohort": current["evaluation_cohort"],
                "label": int(current["label"]),
                "label_status": current["label_status"],
                "episode_id": current["episode_id"],
                "b0_probability": float(current["b0_probability"]),
                "b1_probability": float(current["b1_probability"]),
                "b1_genuine": bool(current["b1_genuine"]),
                "h3_probability": h3_probability,
                "h3_genuine": h3_genuine,
                "h3_state": current["h3_state"],
                "ri_probability": probability,
                "ri_genuine": genuine,
                "ri_state": state,
                "ri_intercept_b": intercept,
                "ri_calibration_samples": len(training),
                "ri_calibration_positive": positives,
                "ri_calibration_negative": negatives,
                "ri_training_earliest_origin": (
                    training["origin_session"].min() if not training.empty else pd.NaT
                ),
                "ri_training_latest_origin": (
                    training["origin_session"].max() if not training.empty else pd.NaT
                ),
                "ri_training_latest_outcome_available_at": (
                    training["outcome_available_at"].max() if not training.empty else pd.NaT
                ),
            }
        )
    return pd.DataFrame.from_records(records)


def evaluate_causal_replay(ledger: pd.DataFrame) -> dict[str, Any]:
    violations: list[str] = []
    for row in ledger.itertuples(index=False):
        origin = pd.Timestamp(row.origin_session)
        as_of = pd.Timestamp(row.forecast_as_of)
        if row.ri_calibration_samples > CALIBRATION_MAX:
            violations.append(f"{origin.date()}: calibration window exceeds {CALIBRATION_MAX}")
        if row.ri_calibration_samples != row.ri_calibration_positive + row.ri_calibration_negative:
            violations.append(f"{origin.date()}: calibration class counts do not sum")
        if row.ri_calibration_samples:
            if not pd.Timestamp(row.ri_training_latest_origin) < origin:
                violations.append(f"{origin.date()}: training origin is not strictly prior")
            if not pd.Timestamp(row.ri_training_latest_outcome_available_at) <= as_of:
                violations.append(f"{origin.date()}: training outcome was unavailable at forecast")

        if row.ri_state == "RI_EMITTED":
            ready = (
                row.ri_calibration_positive >= CALIBRATION_MIN_POSITIVE
                and row.ri_calibration_negative >= CALIBRATION_MIN_NEGATIVE
            )
            replay = apply_intercept(row.h3_probability, row.ri_intercept_b)
            if not row.h3_genuine or not row.ri_genuine or not ready:
                violations.append(f"{origin.date()}: emitted row violates readiness")
            if not math.isclose(replay, row.ri_probability, rel_tol=0.0, abs_tol=1e-12):
                violations.append(f"{origin.date()}: emitted probability replay mismatch")
        elif row.ri_state == "IDENTITY_WARMUP":
            ready = (
                row.ri_calibration_positive >= CALIBRATION_MIN_POSITIVE
                and row.ri_calibration_negative >= CALIBRATION_MIN_NEGATIVE
            )
            if not row.h3_genuine or row.ri_genuine or ready:
                violations.append(f"{origin.date()}: warmup state mismatch")
            if not math.isclose(row.ri_probability, row.h3_probability, rel_tol=0.0, abs_tol=0.0):
                violations.append(f"{origin.date()}: warmup changed H3 probability")
        elif row.ri_state == "ABSTAIN_H3":
            if row.h3_genuine or row.ri_genuine:
                violations.append(f"{origin.date()}: abstention state mismatch")
            if not math.isclose(row.ri_probability, row.h3_probability, rel_tol=0.0, abs_tol=0.0):
                violations.append(f"{origin.date()}: abstention changed H3 probability")
        else:
            violations.append(f"{origin.date()}: unknown RI state {row.ri_state}")

    states = ledger["ri_state"].value_counts().sort_index().to_dict()
    return {
        "passed": not violations,
        "violations": violations,
        "violation_count": len(violations),
        "states": {str(key): int(value) for key, value in states.items()},
        "emitted_intercept_fits": int(ledger["ri_genuine"].sum()),
        "maximum_training_samples": int(ledger["ri_calibration_samples"].max()),
        "maximum_training_outcome_lag_violation": 0 if not violations else None,
    }


def _losses(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, np.ndarray]:
    y = np.asarray(labels, dtype=float)
    p = np.clip(np.asarray(probabilities, dtype=float), PROBABILITY_CLIP, 1 - PROBABILITY_CLIP)
    return {
        "brier": np.square(p - y),
        "log_loss": -(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)),
    }


def _circular_indices(n: int, *, block_length: int, draws: int, seed: int) -> np.ndarray:
    if n <= 0 or block_length <= 0 or draws <= 0:
        raise ValueError("Circular block bootstrap needs positive dimensions")
    effective = min(block_length, n)
    blocks = math.ceil(n / effective)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, size=(draws, blocks))
    offsets = np.arange(effective)
    return ((starts[:, :, None] + offsets[None, None, :]) % n).reshape(draws, -1)[:, :n]


def _circular_block_means(
    values: np.ndarray, *, block_length: int, draws: int, seed: int
) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or not len(array) or not np.isfinite(array).all():
        raise ValueError("Circular block bootstrap needs a finite one-dimensional series")
    n = len(array)
    effective = min(block_length, n)
    blocks = math.ceil(n / effective)
    offsets = np.arange(effective)
    rng = np.random.default_rng(seed)
    distribution = np.empty(draws, dtype=float)
    cursor = 0
    while cursor < draws:
        batch = min(BOOTSTRAP_BATCH, draws - cursor)
        starts = rng.integers(0, n, size=(batch, blocks))
        indices = (starts[:, :, None] + offsets[None, None, :]) % n
        indices = indices.reshape(batch, -1)[:, :n]
        distribution[cursor : cursor + batch] = array[indices].mean(axis=1)
        cursor += batch
    return distribution


def block_interval(
    values: Iterable[float], *, block_length: int, draws: int, seed: int
) -> dict[str, float | int | str]:
    array = np.asarray(list(values), dtype=float)
    distribution = _circular_block_means(array, block_length=block_length, draws=draws, seed=seed)
    return {
        "method": "CIRCULAR_BLOCK",
        "observations": len(array),
        "block_length": min(block_length, len(array)),
        "draws": draws,
        "seed": seed,
        "point": float(array.mean()),
        "lower_90": float(np.quantile(distribution, 0.05)),
        "upper_90": float(np.quantile(distribution, 0.95)),
    }


def _calibration_point(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, float]:
    y = np.asarray(labels, dtype=float)
    p = np.clip(np.asarray(probabilities, dtype=float), PROBABILITY_CLIP, 1 - PROBABILITY_CLIP)
    if len(y) != len(p) or not len(y) or len(np.unique(y)) != 2:
        raise ValueError("Calibration needs aligned probabilities with both outcome classes")
    fitted = LogisticRegression(
        penalty=None,
        solver="lbfgs",
        fit_intercept=True,
        max_iter=1500,
        tol=1e-8,
    )
    fitted.fit(logit(p).reshape(-1, 1), y.astype(int))
    return {
        "mean_probability": float(p.mean()),
        "event_rate": float(y.mean()),
        "mean_calibration_gap": float((y - p).mean()),
        "calibration_in_the_large": fit_intercept(p, y),
        "calibration_slope": float(fitted.coef_[0, 0]),
        "brier": float(np.square(p - y).mean()),
        "log_loss": binary_log_loss(y, p),
    }


def calibration_intervals(
    labels: np.ndarray,
    probabilities: np.ndarray,
    *,
    block_length: int,
    draws: int,
    seed: int,
) -> dict[str, Any]:
    y = np.asarray(labels, dtype=float)
    p = np.asarray(probabilities, dtype=float)
    indices = _circular_indices(len(y), block_length=block_length, draws=draws, seed=seed)
    intercepts: list[float] = []
    slopes: list[float] = []
    gaps = (y[indices] - p[indices]).mean(axis=1)
    for sample in indices:
        sample_y = y[sample]
        if len(np.unique(sample_y)) != 2:
            continue
        point = _calibration_point(sample_y, p[sample])
        intercepts.append(point["calibration_in_the_large"])
        slopes.append(point["calibration_slope"])
    minimum = max(10, math.ceil(0.90 * draws))
    if len(intercepts) < minimum:
        raise ResearchError("Too few valid calibration bootstrap draws")

    def interval(values: Sequence[float]) -> dict[str, float | int]:
        array = np.asarray(values, dtype=float)
        return {
            "valid_draws": len(array),
            "lower_90": float(np.quantile(array, 0.05)),
            "upper_90": float(np.quantile(array, 0.95)),
        }

    return {
        "method": "CIRCULAR_BLOCK",
        "observations": len(y),
        "block_length": min(block_length, len(y)),
        "draws": draws,
        "seed": seed,
        "point": _calibration_point(y, p),
        "mean_calibration_gap": {
            "lower_90": float(np.quantile(gaps, 0.05)),
            "upper_90": float(np.quantile(gaps, 0.95)),
        },
        "calibration_in_the_large": interval(intercepts),
        "calibration_slope": interval(slopes),
    }


def fixed_bin_decomposition(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, float]:
    y = np.asarray(labels, dtype=float)
    p = np.asarray(probabilities, dtype=float)
    event_rate = float(y.mean())
    reliability = 0.0
    resolution = 0.0
    for lower, upper in zip(PROBABILITY_BINS[:-1], PROBABILITY_BINS[1:], strict=True):
        mask = (p >= lower) & (p < upper)
        if not mask.any():
            continue
        weight = float(mask.mean())
        reliability += weight * float((p[mask].mean() - y[mask].mean()) ** 2)
        resolution += weight * float((y[mask].mean() - event_rate) ** 2)
    return {
        "reliability": reliability,
        "weighted_rms_calibration_gap": math.sqrt(reliability),
        "resolution": resolution,
    }


def fixed_bin_wrms_interval(
    labels: np.ndarray,
    probabilities: np.ndarray,
    *,
    block_length: int,
    draws: int,
) -> dict[str, Any]:
    y = np.asarray(labels, dtype=float)
    p = np.asarray(probabilities, dtype=float)
    indices = _circular_indices(
        len(y), block_length=block_length, draws=draws, seed=BOOTSTRAP_SEED + 303 + block_length
    )
    sampled_p = p[indices]
    sampled_y = y[indices]
    squared = np.zeros(draws, dtype=float)
    for lower, upper in zip(PROBABILITY_BINS[:-1], PROBABILITY_BINS[1:], strict=True):
        mask = (sampled_p >= lower) & (sampled_p < upper)
        counts = mask.sum(axis=1)
        rate = np.divide(
            (mask * sampled_y).sum(axis=1), counts, out=np.zeros(draws), where=counts > 0
        )
        mean_p = np.divide(
            (mask * sampled_p).sum(axis=1), counts, out=np.zeros(draws), where=counts > 0
        )
        squared += (counts / len(y)) * np.square(rate - mean_p)
    distribution = np.sqrt(squared)
    point = fixed_bin_decomposition(y, p)["weighted_rms_calibration_gap"]
    return {
        "method": "FIXED_BIN_CIRCULAR_BLOCK",
        "observations": len(y),
        "block_length": min(block_length, len(y)),
        "draws": draws,
        "point": point,
        "lower_90": float(np.quantile(distribution, 0.05)),
        "upper_90": float(np.quantile(distribution, 0.95)),
    }


def fixed_bin_table(frame: pd.DataFrame, probability_column: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lower, upper in zip(PROBABILITY_BINS[:-1], PROBABILITY_BINS[1:], strict=True):
        cell = frame.loc[frame[probability_column].ge(lower) & frame[probability_column].lt(upper)]
        positive = cell.loc[cell["label"].eq(1) & cell["episode_id"].notna()]
        origins = len(cell)
        episodes = int(positive["episode_id"].nunique())
        rows.append(
            {
                "lower": lower,
                "upper": upper,
                "origins": origins,
                "positive_origins": int(cell["label"].sum()) if origins else 0,
                "positive_episodes": episodes,
                "mean_probability": float(cell[probability_column].mean()) if origins else None,
                "event_rate": float(cell["label"].mean()) if origins else None,
                "literal_supported": origins >= BIN_MIN_ORIGINS and episodes >= BIN_MIN_EPISODES,
            }
        )
    return rows


def _period_point(frame: pd.DataFrame, probability_column: str) -> dict[str, Any]:
    point = _calibration_point(
        frame["label"].to_numpy(dtype=float), frame[probability_column].to_numpy(dtype=float)
    )
    decomposition = fixed_bin_decomposition(
        frame["label"].to_numpy(dtype=float), frame[probability_column].to_numpy(dtype=float)
    )
    return {
        "origins": len(frame),
        "positive_origins": int(frame["label"].sum()),
        "positive_episodes": int(
            frame.loc[frame["label"].eq(1) & frame["episode_id"].notna(), "episode_id"].nunique()
        ),
        **point,
        **decomposition,
    }


def _period_gap_shift(
    left: pd.DataFrame,
    right: pd.DataFrame,
    probability_column: str,
    *,
    block_length: int,
    draws: int,
) -> dict[str, Any]:
    left_gap = left["label"].to_numpy(dtype=float) - left[probability_column].to_numpy(dtype=float)
    right_gap = right["label"].to_numpy(dtype=float) - right[probability_column].to_numpy(
        dtype=float
    )
    left_dist = _circular_block_means(
        left_gap,
        block_length=block_length,
        draws=draws,
        seed=BOOTSTRAP_SEED + 101 + block_length,
    )
    right_dist = _circular_block_means(
        right_gap,
        block_length=block_length,
        draws=draws,
        seed=BOOTSTRAP_SEED + 202 + block_length,
    )
    difference = right_dist - left_dist
    return {
        "point": float(right_gap.mean() - left_gap.mean()),
        "lower_90": float(np.quantile(difference, 0.05)),
        "upper_90": float(np.quantile(difference, 0.95)),
        "block_length": block_length,
        "draws": draws,
    }


def evaluate_calibration_repair(formal: pd.DataFrame, *, draws: int) -> dict[str, Any]:
    years = pd.to_datetime(formal["origin_session"]).dt.year
    periods = {
        "2017_2019": formal.loc[years.le(2019)].reset_index(drop=True),
        "2020_2023": formal.loc[years.between(2020, 2023)].reset_index(drop=True),
        "2024_2026": formal.loc[years.ge(2024)].reset_index(drop=True),
        "ALL": formal,
    }
    if any(cell.empty or cell["label"].nunique() != 2 for cell in periods.values()):
        raise ResearchError("Frozen calibration periods lack both outcome classes")
    intervals = {
        str(block): calibration_intervals(
            formal["label"].to_numpy(dtype=float),
            formal["ri_probability"].to_numpy(dtype=float),
            block_length=block,
            draws=draws,
            seed=BOOTSTRAP_SEED + block,
        )
        for block in BOOTSTRAP_BLOCKS
    }
    wrms = {
        str(block): fixed_bin_wrms_interval(
            formal["label"].to_numpy(dtype=float),
            formal["ri_probability"].to_numpy(dtype=float),
            block_length=block,
            draws=draws,
        )
        for block in BOOTSTRAP_BLOCKS
    }
    period_points = {
        name: {
            "h3": _period_point(cell, "h3_probability"),
            "ri": _period_point(cell, "ri_probability"),
        }
        for name, cell in periods.items()
    }
    drift = {
        str(block): _period_gap_shift(
            periods["2020_2023"],
            periods["2024_2026"],
            "ri_probability",
            block_length=block,
            draws=draws,
        )
        for block in BOOTSTRAP_BLOCKS
    }
    interval_pass = all(
        float(intervals[str(block)]["calibration_in_the_large"]["lower_90"])
        >= CALIBRATION_ODDS_LOWER
        and float(intervals[str(block)]["calibration_in_the_large"]["upper_90"])
        <= CALIBRATION_ODDS_UPPER
        and float(intervals[str(block)]["calibration_slope"]["lower_90"]) >= CALIBRATION_SLOPE_LOWER
        and float(intervals[str(block)]["calibration_slope"]["upper_90"]) <= CALIBRATION_SLOPE_UPPER
        and float(wrms[str(block)]["upper_90"]) <= CALIBRATION_WRMS_MAX
        for block in BOOTSTRAP_BLOCKS
    )
    regime_gaps_pass = all(
        abs(float(period_points[name]["ri"]["mean_calibration_gap"])) <= REGIME_GAP_MAX
        for name in ("2020_2023", "2024_2026")
    )
    drift_pass = all(
        abs(float(drift[str(block)]["point"])) <= REGIME_GAP_MAX
        and float(drift[str(block)]["lower_90"]) <= 0.0
        and float(drift[str(block)]["upper_90"]) >= 0.0
        for block in BOOTSTRAP_BLOCKS
    )
    return {
        "passed": interval_pass and regime_gaps_pass and drift_pass,
        "interval_gate_pass": interval_pass,
        "regime_gap_gate_pass": regime_gaps_pass,
        "regime_shift_gate_pass": drift_pass,
        "margins": {
            "calibration_in_the_large": [CALIBRATION_ODDS_LOWER, CALIBRATION_ODDS_UPPER],
            "calibration_slope": [CALIBRATION_SLOPE_LOWER, CALIBRATION_SLOPE_UPPER],
            "fixed_bin_wrms_upper_max": CALIBRATION_WRMS_MAX,
            "regime_gap_absolute_max": REGIME_GAP_MAX,
            "regime_shift_absolute_max": REGIME_GAP_MAX,
        },
        "full_intervals": intervals,
        "fixed_bin_wrms_intervals": wrms,
        "period_points": period_points,
        "regime_gap_shift": drift,
    }


def _paired_comparison(
    frame: pd.DataFrame, reference: str, candidate: str, *, draws: int
) -> dict[str, Any]:
    labels = frame["label"].to_numpy(dtype=float)
    reference_losses = _losses(labels, frame[reference].to_numpy(dtype=float))
    candidate_losses = _losses(labels, frame[candidate].to_numpy(dtype=float))
    return {
        "origins": len(frame),
        "positive_origins": int(labels.sum()),
        "positive_episodes": int(
            frame.loc[frame["label"].eq(1) & frame["episode_id"].notna(), "episode_id"].nunique()
        ),
        "intervals": {
            str(block): {
                loss_name: block_interval(
                    reference_losses[loss_name] - candidate_losses[loss_name],
                    block_length=block,
                    draws=draws,
                    seed=BOOTSTRAP_SEED + block,
                )
                for loss_name in ("brier", "log_loss")
            }
            for block in BOOTSTRAP_BLOCKS
        },
    }


def evaluate_proper_score(formal: pd.DataFrame, *, draws: int) -> dict[str, Any]:
    b1_common = formal.loc[formal["b1_genuine"].astype(bool)].reset_index(drop=True)
    if b1_common.empty:
        raise ResearchError("RI/H3/B1 nested genuine common cohort is empty")
    comparisons = {
        "ri>h3": _paired_comparison(formal, "h3_probability", "ri_probability", draws=draws),
        "ri>b0": _paired_comparison(formal, "b0_probability", "ri_probability", draws=draws),
        "ri>b1": _paired_comparison(b1_common, "b1_probability", "ri_probability", draws=draws),
    }
    interval_pass = all(
        float(comparisons[name]["intervals"][str(block)][loss]["point"]) > 0.0
        and float(comparisons[name]["intervals"][str(block)][loss]["lower_90"]) > 0.0
        for name in comparisons
        for block in BOOTSTRAP_BLOCKS
        for loss in ("brier", "log_loss")
    )
    years = pd.to_datetime(formal["origin_session"]).dt.year
    periods: dict[str, Any] = {}
    period_pass = True
    for name, mask in {
        "2020_2023": years.between(2020, 2023),
        "2024_2026": years.ge(2024),
    }.items():
        cell = formal.loc[mask]
        labels = cell["label"].to_numpy(dtype=float)
        h3 = _losses(labels, cell["h3_probability"].to_numpy(dtype=float))
        ri = _losses(labels, cell["ri_probability"].to_numpy(dtype=float))
        periods[name] = {
            loss: float((h3[loss] - ri[loss]).mean()) for loss in ("brier", "log_loss")
        }
        period_pass = period_pass and all(value > 0.0 for value in periods[name].values())
    return {
        "passed": interval_pass and period_pass,
        "paired_interval_gate_pass": interval_pass,
        "period_direction_gate_pass": period_pass,
        "comparisons": comparisons,
        "ri_vs_h3_period_points": periods,
    }


def evaluate_resolution_retention(formal: pd.DataFrame) -> dict[str, Any]:
    labels = formal["label"].to_numpy(dtype=float)
    h3 = fixed_bin_decomposition(labels, formal["h3_probability"].to_numpy(dtype=float))
    ri = fixed_bin_decomposition(labels, formal["ri_probability"].to_numpy(dtype=float))
    bins = fixed_bin_table(formal, "ri_probability")
    supported = [row for row in bins if row["literal_supported"]]
    ordinal = len(supported) >= 4 and all(
        float(right["event_rate"]) >= float(left["event_rate"])
        for left, right in zip(supported, supported[1:], strict=False)
    )
    resolution_pass = float(ri["resolution"]) >= float(h3["resolution"])
    return {
        "passed": resolution_pass and ordinal,
        "resolution_noninferiority_pass": resolution_pass,
        "supported_bin_ordering_pass": ordinal,
        "h3": h3,
        "ri": ri,
        "fixed_probability_bins": bins,
    }


def verdict_from_gates(gates: dict[str, bool]) -> str:
    if not gates["CAUSAL_REPLAY"]:
        return "INVALID_EVALUATION"
    if not gates["CALIBRATION_REPAIR"]:
        return "CALIBRATION_REPAIR_NOT_ESTABLISHED"
    if not gates["PROPER_SCORE"] or not gates["RESOLUTION_RETENTION"]:
        return "CALIBRATION_REPAIR_REJECTED_FOR_INFORMATION_LOSS"
    return "ROLLING_INTERCEPT_CALIBRATION_SUPPORTED"


def _format(value: object, digits: int = 6) -> str:
    if value is None:
        return "NA"
    if isinstance(value, bool):
        return "PASS" if value else "FAIL"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{digits}f}"
    return str(value)


def render_report(evidence: dict[str, Any]) -> str:
    verdict = str(evidence["verdict"])
    calibration = evidence["calibration_repair"]
    proper = evidence["proper_score"]
    resolution = evidence["resolution_retention"]
    cohort = evidence["cohort"]
    lines = [
        "# E15 H3 causal rolling-intercept calibration",
        "",
        f"Verdict: `{verdict}`",
        "",
        "Authority: `HISTORICAL_RESEARCH_ONLY / NO_PRODUCT_POSITION_ORDER_OR_TRADING_AUTHORITY`",
        "",
        "## Scientific decision",
        "",
    ]
    if verdict == "ROLLING_INTERCEPT_CALIBRATION_SUPPORTED":
        lines.extend(
            [
                "唯一冻结的 RI252 候选同时通过因果重放、校准修复、proper score 和分辨率保留门。",
                "三日轨迹只恢复未来另一次冻结评估资格；本轮没有拟合轨迹，也没有产品晋升。",
            ]
        )
    elif verdict == "CALIBRATION_REPAIR_NOT_ESTABLISHED":
        lines.extend(
            [
                "RI252 未按冻结门消除制度性校准偏差，因此校准修复主张不成立。",
                "本轮停止，不搜索第二个校准器；H3 历史天气传感器结论保留，三日轨迹继续阻断。",
            ]
        )
    elif verdict == "CALIBRATION_REPAIR_REJECTED_FOR_INFORMATION_LOSS":
        lines.extend(
            [
                "RI252 达到校准修复门，但没有同时保住冻结的 proper-score 或分辨率证据。",
                "因此候选被拒绝，本轮停止，三日轨迹继续阻断。",
            ]
        )
    else:
        lines.append("冻结输入或因果重放不完整，本次运行无科学裁决。")

    lines.extend(
        [
            "",
            "## Frozen design and cohort",
            "",
            f"- Contract: `{evidence['contract']}`.",
            f"- Calibration memory: last {CALIBRATION_MAX} matured genuine H3 origins.",
            f"- Readiness: {CALIBRATION_MIN_POSITIVE} positives and {CALIBRATION_MIN_NEGATIVE} negatives.",
            f"- Formal RI/H3/B0 cohort: {cohort['formal_origins']} origins, "
            f"{cohort['formal_positive_origins']} positives, {cohort['formal_positive_episodes']} episodes.",
            f"- Nested genuine B1 cohort: {cohort['b1_common_origins']} origins.",
            f"- Bootstrap: {evidence['design']['bootstrap_draws']} draws at 20/84-session blocks.",
            "",
            "## Gate results",
            "",
            "| gate | result |",
            "|---|---|",
        ]
    )
    for name, passed in evidence["gates"].items():
        lines.append(f"| `{name}` | `{_format(passed)}` |")

    lines.extend(
        [
            "",
            "## Calibration repair",
            "",
            "| period | model | origins | mean p | event rate | gap | slope |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for period in ("2017_2019", "2020_2023", "2024_2026", "ALL"):
        for model in ("h3", "ri"):
            point = calibration["period_points"][period][model]
            lines.append(
                f"| `{period}` | `{model}` | {point['origins']} | "
                f"{_format(point['mean_probability'], 4)} | {_format(point['event_rate'], 4)} | "
                f"{_format(point['mean_calibration_gap'], 4)} | "
                f"{_format(point['calibration_slope'], 4)} |"
            )
    lines.extend(["", "RI 2020–2023 to 2024–2026 gap shift:", ""])
    lines.extend(["| block | point | 90% interval |", "|---:|---:|---:|"])
    for block in BOOTSTRAP_BLOCKS:
        cell = calibration["regime_gap_shift"][str(block)]
        lines.append(
            f"| {block} | {_format(cell['point'], 4)} | "
            f"[{_format(cell['lower_90'], 4)}, {_format(cell['upper_90'], 4)}] |"
        )

    lines.extend(
        [
            "",
            "## Proper score",
            "",
            "Positive values favor RI.",
            "",
            "| comparison | block | Brier point [90%] | log-loss point [90%] |",
            "|---|---:|---:|---:|",
        ]
    )
    for comparison in ("ri>h3", "ri>b0", "ri>b1"):
        for block in BOOTSTRAP_BLOCKS:
            cell = proper["comparisons"][comparison]["intervals"][str(block)]
            brier = cell["brier"]
            log_loss = cell["log_loss"]
            lines.append(
                f"| `{comparison}` | {block} | {_format(brier['point'])} "
                f"[{_format(brier['lower_90'])}, {_format(brier['upper_90'])}] | "
                f"{_format(log_loss['point'])} "
                f"[{_format(log_loss['lower_90'])}, {_format(log_loss['upper_90'])}] |"
            )

    lines.extend(
        [
            "",
            "## Resolution and probability ordering",
            "",
            "| model | reliability | WRMS gap | resolution |",
            "|---|---:|---:|---:|",
            f"| `h3` | {_format(resolution['h3']['reliability'])} | "
            f"{_format(resolution['h3']['weighted_rms_calibration_gap'])} | "
            f"{_format(resolution['h3']['resolution'])} |",
            f"| `ri` | {_format(resolution['ri']['reliability'])} | "
            f"{_format(resolution['ri']['weighted_rms_calibration_gap'])} | "
            f"{_format(resolution['ri']['resolution'])} |",
            "",
            f"Supported-bin ordering: `{_format(resolution['supported_bin_ordering_pass'])}`.",
            "",
            "## Causal and authority boundary",
            "",
            f"Causal replay violations: {evidence['causal_replay']['violation_count']}; "
            f"emitted intercept fits: {evidence['causal_replay']['emitted_intercept_fits']}.",
            "H3 abstentions and warm-up probabilities were preserved exactly. No H3 feature, target, clock, "
            "V3 product value, Prospective 001 record, action, position, order or trade was changed.",
            "",
            "## Engineering outputs",
            "",
            f"- OOF ledger: `{LEDGER_OUTPUT}`.",
            f"- Machine evidence: `{EVIDENCE_OUTPUT}`.",
            f"- Report: `{REPORT_OUTPUT}`.",
            "",
        ]
    )
    return "\n".join(lines)


def run(root: Path, *, draws: int = DEFAULT_DRAWS, write_outputs: bool = True) -> dict[str, Any]:
    if draws <= 0:
        raise ValueError("draws must be positive")
    if write_outputs and draws != DEFAULT_DRAWS:
        raise ResearchError(f"Formal output requires exactly {DEFAULT_DRAWS} bootstrap draws")
    panel, identities = load_frozen_inputs(root)
    ledger = build_rolling_intercept_ledger(panel)
    causal = evaluate_causal_replay(ledger)
    if not causal["passed"]:
        evidence = {
            "contract": CONTRACT_ID,
            "input_identity": identities,
            "causal_replay": causal,
            "gates": {
                "CAUSAL_REPLAY": False,
                "CALIBRATION_REPAIR": False,
                "PROPER_SCORE": False,
                "RESOLUTION_RETENTION": False,
            },
            "verdict": "INVALID_EVALUATION",
            "authority": {
                "research_only": True,
                "v3_change": False,
                "prospective_change": False,
                "position_order_or_trading": False,
            },
        }
        return evidence

    formal = ledger.loc[ledger["ri_genuine"].astype(bool)].sort_values(
        "origin_session", kind="stable"
    )
    formal = formal.reset_index(drop=True)
    if formal.empty:
        raise ResearchError("Rolling-intercept candidate has no formal scoring origins")
    b1_common = formal.loc[formal["b1_genuine"].astype(bool)]
    calibration = evaluate_calibration_repair(formal, draws=draws)
    proper = evaluate_proper_score(formal, draws=draws)
    resolution = evaluate_resolution_retention(formal)
    gates = {
        "CAUSAL_REPLAY": bool(causal["passed"]),
        "CALIBRATION_REPAIR": bool(calibration["passed"]),
        "PROPER_SCORE": bool(proper["passed"]),
        "RESOLUTION_RETENTION": bool(resolution["passed"]),
    }
    verdict = verdict_from_gates(gates)
    evidence = {
        "contract": CONTRACT_ID,
        "verdict": verdict,
        "trajectory_eligibility": (
            "ELIGIBLE_FOR_SEPARATE_FROZEN_EVALUATION"
            if verdict == "ROLLING_INTERCEPT_CALIBRATION_SUPPORTED"
            else "BLOCKED"
        ),
        "authority": {
            "research_only": True,
            "v3_change": False,
            "prospective_change": False,
            "position_order_or_trading": False,
        },
        "input_identity": identities,
        "design": {
            "formula": "logit(p_ri_t)=logit(p_h3_t)+b_t",
            "slope": 1.0,
            "calibration_max": CALIBRATION_MAX,
            "calibration_min_positive": CALIBRATION_MIN_POSITIVE,
            "calibration_min_negative": CALIBRATION_MIN_NEGATIVE,
            "bootstrap_draws": draws,
            "bootstrap_blocks": list(BOOTSTRAP_BLOCKS),
            "bootstrap_seed": BOOTSTRAP_SEED,
            "model_or_window_searches": 0,
        },
        "cohort": {
            "input_origins": len(ledger),
            "formal_origins": len(formal),
            "formal_positive_origins": int(formal["label"].sum()),
            "formal_positive_episodes": int(
                formal.loc[
                    formal["label"].eq(1) & formal["episode_id"].notna(), "episode_id"
                ].nunique()
            ),
            "formal_start": formal["origin_session"].min(),
            "formal_end": formal["origin_session"].max(),
            "b1_common_origins": len(b1_common),
        },
        "causal_replay": causal,
        "calibration_repair": calibration,
        "proper_score": proper,
        "resolution_retention": resolution,
        "gates": gates,
    }
    if write_outputs:
        output_dir = _rooted(root, OUTPUT_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        ledger.to_parquet(_rooted(root, LEDGER_OUTPUT), index=False)
        _rooted(root, EVIDENCE_OUTPUT).write_text(
            json.dumps(_json_ready(evidence), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _rooted(root, REPORT_OUTPUT).write_text(render_report(evidence), encoding="utf-8")
    return evidence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the frozen E15 RI252 calibration evaluation")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--draws", type=int, default=DEFAULT_DRAWS)
    args = parser.parse_args(argv)
    evidence = run(args.root.resolve(), draws=args.draws)
    print(evidence["verdict"])
    print(_rooted(args.root.resolve(), REPORT_OUTPUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
