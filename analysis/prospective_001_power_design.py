#!/usr/bin/env python3
"""Reproduce the read-only Prospective 001 P0 power-design evidence.

This program deliberately reads only the frozen probability ledgers and the
weather-station acceptance calendar.  It does not write artifacts, inspect an
economic probe, read product prices, or alter a model/configuration.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import norm

from matvix.constants import (
    BASE_RATE_ONLY_EVENTS,
    EVENT_HORIZONS,
    FEATURE_CONDITIONAL_EVENTS,
)
from matvix.probability.walk_forward import ProbabilitySpec, validation_as_of

ROOT = Path(__file__).resolve().parents[1]
OOF_PATH = ROOT / "data" / "probability" / "oof_ledger.parquet"
TARGET_PATH = ROOT / "data" / "probability" / "target_ledger.parquet"
CALENDAR_PATH = ROOT / "outputs" / "v3_station_acceptance" / "daily_ledger.parquet"

RESOLVED = frozenset({"OBSERVED_0", "OBSERVED_1"})
PRIMARY_BLOCK_SESSIONS = 20
BLOCK_SENSITIVITY = (10, 20, 40)
SKILL_SENSITIVITY = (0.02, 0.05, 0.10, 0.15)
BOOTSTRAP_REPLICATIONS = 10_000
BOOTSTRAP_SEED = 20_260_823

# These are P0 recommendations, not frozen contract values.
EVIDENCE_FLOOR = {
    "minimum_calendar_months": 36,
    "minimum_resolved_predictions": 504,
    "minimum_positive_outcomes": 50,
    "minimum_negative_outcomes": 50,
    "minimum_positive_episodes": 20,
    "minimum_negative_horizon_blocks": 30,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_identity(path: Path) -> dict[str, object]:
    return {
        "path": str(path.relative_to(ROOT)),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DatetimeIndex]:
    oof = pd.read_parquet(OOF_PATH)
    targets = pd.read_parquet(TARGET_PATH)
    calendar = pd.read_parquet(CALENDAR_PATH)

    oof["prediction_date"] = pd.to_datetime(oof["prediction_date"]).dt.normalize()
    targets["prediction_date"] = pd.to_datetime(targets["prediction_date"]).dt.normalize()
    sessions = pd.DatetimeIndex(
        pd.to_datetime(calendar["session_date"]).dt.normalize().sort_values().unique()
    )

    joined = oof.merge(
        targets[
            [
                "event_id",
                "prediction_date",
                "label",
                "label_status",
                "outcome_available_at",
            ]
        ],
        on=["event_id", "prediction_date"],
        how="left",
        validate="one_to_one",
        suffixes=("_oof", "_target"),
    )
    if joined["label_status_target"].isna().any():
        raise ValueError("An OOF row is absent from the target ledger")
    if not joined["label_status_oof"].eq(joined["label_status_target"]).all():
        raise ValueError("OOF and target label_status values differ")
    resolved = joined["label_status_oof"].isin(RESOLVED)
    if not np.allclose(
        joined.loc[resolved, "label_oof"],
        joined.loc[resolved, "label_target"],
    ):
        raise ValueError("OOF and target labels differ")
    oof_available = pd.to_datetime(joined["outcome_available_at_oof"], utc=True)
    target_available = pd.to_datetime(joined["outcome_available_at_target"], utc=True)
    timestamps_match = oof_available.eq(target_available) | (
        oof_available.isna() & target_available.isna()
    )
    if not timestamps_match.all():
        raise ValueError("OOF and target outcome availability timestamps differ")
    if not oof["prediction_date"].isin(sessions).all():
        raise ValueError("An OOF prediction date is absent from the acceptance calendar")
    return oof, targets, sessions


def _mature_rows(oof: pd.DataFrame, event: str) -> pd.DataFrame:
    rows = oof.loc[oof["event_id"].eq(event) & oof["label_status"].isin(RESOLVED)].sort_values(
        "prediction_date"
    )
    if event not in BASE_RATE_ONLY_EVENTS:
        rows = rows.loc[rows["calibration_method"].eq("ROLLING_INTERCEPT_252")]
    return rows.reset_index(drop=True)


def _positive_episode_count(session_indices: np.ndarray, labels: np.ndarray, horizon: int) -> int:
    positive = session_indices[labels == 1]
    if not len(positive):
        return 0
    return int(np.r_[True, np.diff(positive) > horizon].sum())


def _negative_block_count(
    session_indices: np.ndarray,
    labels: np.ndarray,
    horizon: int,
    *,
    anchor: int,
) -> int:
    if not len(session_indices):
        return 0
    block_ids = (session_indices - anchor) // horizon
    return int(sum(not labels[block_ids == block_id].any() for block_id in np.unique(block_ids)))


def _calendar_blocks(
    session_indices: np.ndarray,
    *values: np.ndarray,
    block_sessions: int,
) -> tuple[np.ndarray, list[np.ndarray]]:
    block_ids = (session_indices - int(session_indices.min())) // block_sessions
    block_count = int(block_ids.max()) + 1
    counts = np.zeros(block_count, dtype=int)
    np.add.at(counts, block_ids, 1)
    totals: list[np.ndarray] = []
    for value in values:
        aggregate = np.zeros(block_count, dtype=float)
        np.add.at(aggregate, block_ids, value)
        totals.append(aggregate)
    return counts, totals


def _skill_interval(
    session_indices: np.ndarray,
    loss_improvement: np.ndarray,
    base_loss: np.ndarray,
    *,
    block_sessions: int,
    seed: int,
) -> dict[str, object]:
    counts, totals = _calendar_blocks(
        session_indices,
        loss_improvement,
        base_loss,
        block_sessions=block_sessions,
    )
    improvement_by_block, base_by_block = totals
    rng = np.random.default_rng(seed)
    draws = rng.integers(
        0,
        len(counts),
        size=(BOOTSTRAP_REPLICATIONS, len(counts)),
    )
    sampled_improvement = improvement_by_block[draws].sum(axis=1)
    sampled_base = base_by_block[draws].sum(axis=1)
    bootstrap_skill = sampled_improvement / sampled_base
    return {
        "calendar_blocks": len(counts),
        "nonempty_blocks": int((counts > 0).sum()),
        "point_skill": float(loss_improvement.sum() / base_loss.sum()),
        "one_sided_95_lower": float(np.quantile(bootstrap_skill, 0.05)),
        "two_sided_95": [
            float(np.quantile(bootstrap_skill, 0.025)),
            float(np.quantile(bootstrap_skill, 0.975)),
        ],
    }


def _required_power_years(
    session_indices: np.ndarray,
    loss_improvement: np.ndarray,
    base_loss: np.ndarray,
    *,
    block_sessions: int,
) -> dict[str, float]:
    centered = loss_improvement - loss_improvement.mean()
    counts, totals = _calendar_blocks(
        session_indices,
        centered,
        block_sessions=block_sessions,
    )
    centered_by_block = totals[0]
    mean_observations = float(counts.mean())
    block_standard_deviation = float(centered_by_block.std(ddof=1))
    # One-sided alpha=5%, power=80%.  The empirical calendar-block variance is
    # retained, while the observed mean effect is removed before each target
    # alternative is imposed.
    normal_distance = float(norm.ppf(0.95) + norm.ppf(0.80))
    base_brier = float(base_loss.mean())
    result: dict[str, float] = {}
    for skill in SKILL_SENSITIVITY:
        target_loss_improvement = skill * base_brier
        required_blocks = (
            normal_distance
            * block_standard_deviation
            / (target_loss_improvement * mean_observations)
        ) ** 2
        result[f"skill_{skill:.2f}"] = float(required_blocks * block_sessions / 252.0)
    return result


def _validation_coverage(oof: pd.DataFrame, event: str, rows: pd.DataFrame) -> pd.Series:
    event_oof = oof.loc[oof["event_id"].eq(event)].sort_values("prediction_date")
    spec = ProbabilitySpec()
    accepted = {
        date: bool(validation_as_of(event_oof, date, spec).get("accepted", False))
        for date in event_oof["prediction_date"]
    }
    return rows["prediction_date"].map(accepted).fillna(False).astype(bool)


def _yearly_gate_replay(
    rows: pd.DataFrame,
    session_indices: np.ndarray,
    sessions: pd.DatetimeIndex,
    event: str,
) -> list[dict[str, object]]:
    horizon = EVENT_HORIZONS[event]
    labels = rows["label"].to_numpy(dtype=int)
    first_year = int(rows["prediction_date"].dt.year.min())
    last_year = int(rows["prediction_date"].dt.year.max())
    session_location = {date: index for index, date in enumerate(sessions)}
    result: list[dict[str, object]] = []
    for year in range(first_year, last_year + 1):
        candidates = sessions[(sessions.year == year) & (sessions >= rows["prediction_date"].min())]
        if not len(candidates):
            continue
        anchor_date = pd.Timestamp(candidates[0])
        anchor = session_location[anchor_date]
        achieved_at: int | None = None
        achieved_counts: dict[str, int] | None = None
        minimum_end_date = anchor_date + pd.DateOffset(
            months=EVIDENCE_FLOOR["minimum_calendar_months"]
        )
        for end in range(anchor, int(session_indices.max()) + 1):
            if sessions[end] < minimum_end_date:
                continue
            selected = (session_indices >= anchor) & (session_indices <= end)
            selected_indices = session_indices[selected]
            selected_labels = labels[selected]
            counts = {
                "resolved_predictions": int(selected.sum()),
                "positive_outcomes": int(selected_labels.sum()),
                "negative_outcomes": int(len(selected_labels) - selected_labels.sum()),
                "positive_episodes": _positive_episode_count(
                    selected_indices, selected_labels, horizon
                ),
                "negative_horizon_blocks": _negative_block_count(
                    selected_indices,
                    selected_labels,
                    horizon,
                    anchor=anchor,
                ),
            }
            if (
                counts["resolved_predictions"] >= EVIDENCE_FLOOR["minimum_resolved_predictions"]
                and counts["positive_outcomes"] >= EVIDENCE_FLOOR["minimum_positive_outcomes"]
                and counts["negative_outcomes"] >= EVIDENCE_FLOOR["minimum_negative_outcomes"]
                and counts["positive_episodes"] >= EVIDENCE_FLOOR["minimum_positive_episodes"]
                and counts["negative_horizon_blocks"]
                >= EVIDENCE_FLOOR["minimum_negative_horizon_blocks"]
            ):
                achieved_at = end
                achieved_counts = counts
                break
        record: dict[str, object] = {"anchor": anchor_date.date().isoformat()}
        if achieved_at is None:
            record["status"] = "RIGHT_CENSORED"
        else:
            achieved_date = sessions[achieved_at]
            record.update(
                {
                    "status": "ACHIEVED",
                    "achieved_at": achieved_date.date().isoformat(),
                    "elapsed_years": float((achieved_date - anchor_date).days / 365.2425),
                    "counts": achieved_counts,
                }
            )
        result.append(record)
    return result


def _event_report(
    oof: pd.DataFrame,
    sessions: pd.DatetimeIndex,
    event: str,
    event_number: int,
) -> dict[str, Any]:
    rows = _mature_rows(oof, event)
    session_location = {date: index for index, date in enumerate(sessions)}
    session_indices = rows["prediction_date"].map(session_location).to_numpy(dtype=int)
    labels = rows["label"].to_numpy(dtype=int)
    horizon = EVENT_HORIZONS[event]
    span_years = float(
        (rows["prediction_date"].max() - rows["prediction_date"].min()).days / 365.2425
    )
    positive_episodes = _positive_episode_count(session_indices, labels, horizon)
    negative_blocks = _negative_block_count(
        session_indices,
        labels,
        horizon,
        anchor=int(session_indices.min()),
    )
    report: dict[str, Any] = {
        "horizon_sessions": horizon,
        "mature_probability_rule": (
            "NOT_APPLICABLE_BASE_RATE_ONLY"
            if event in BASE_RATE_ONLY_EVENTS
            else "ROLLING_INTERCEPT_252"
        ),
        "first_prediction": rows["prediction_date"].min().date().isoformat(),
        "last_resolved_prediction": rows["prediction_date"].max().date().isoformat(),
        "span_years": span_years,
        "resolved_predictions": len(rows),
        "positive_outcomes": int(labels.sum()),
        "negative_outcomes": int(len(labels) - labels.sum()),
        "positive_episodes": positive_episodes,
        "negative_horizon_blocks": negative_blocks,
        "annualized": {
            "resolved_predictions": float(len(rows) / span_years),
            "positive_outcomes": float(labels.sum() / span_years),
            "negative_outcomes": float((len(labels) - labels.sum()) / span_years),
            "positive_episodes": float(positive_episodes / span_years),
            "negative_horizon_blocks": float(negative_blocks / span_years),
        },
    }
    if event in BASE_RATE_ONLY_EVENTS:
        report["model_skill"] = "NOT_APPLICABLE"
        return report

    model_probability = rows["published_probability"].to_numpy(dtype=float)
    base_probability = rows["base_rate_at_prediction"].to_numpy(dtype=float)
    base_loss = (base_probability - labels) ** 2
    model_loss = (model_probability - labels) ** 2
    loss_improvement = base_loss - model_loss
    accepted = _validation_coverage(oof, event, rows)
    as_published_probability = np.where(accepted.to_numpy(), model_probability, base_probability)
    report.update(
        {
            "historical_descriptive_only": {
                "candidate_model_skill": float(loss_improvement.sum() / base_loss.sum()),
                "causal_validation_coverage": float(accepted.mean()),
                "publication_policy_skill": float(
                    1.0 - np.mean((as_published_probability - labels) ** 2) / base_loss.mean()
                ),
            },
            "cluster_bootstrap_candidate_skill": {
                str(block): _skill_interval(
                    session_indices,
                    loss_improvement,
                    base_loss,
                    block_sessions=block,
                    seed=BOOTSTRAP_SEED + event_number * 100 + block,
                )
                for block in BLOCK_SENSITIVITY
            },
            "asymptotic_years_for_80_percent_power": {
                str(block): _required_power_years(
                    session_indices,
                    loss_improvement,
                    base_loss,
                    block_sessions=block,
                )
                for block in BLOCK_SENSITIVITY
            },
            "recommended_floor_replay": _yearly_gate_replay(
                rows,
                session_indices,
                sessions,
                event,
            ),
        }
    )
    annualized = report["annualized"]
    assert isinstance(annualized, dict)
    report["idealized_years_to_recommended_floor"] = max(
        EVIDENCE_FLOOR["minimum_calendar_months"] / 12.0,
        EVIDENCE_FLOOR["minimum_resolved_predictions"] / float(annualized["resolved_predictions"]),
        EVIDENCE_FLOOR["minimum_positive_outcomes"] / float(annualized["positive_outcomes"]),
        EVIDENCE_FLOOR["minimum_negative_outcomes"] / float(annualized["negative_outcomes"]),
        EVIDENCE_FLOOR["minimum_positive_episodes"] / float(annualized["positive_episodes"]),
        EVIDENCE_FLOOR["minimum_negative_horizon_blocks"]
        / float(annualized["negative_horizon_blocks"]),
    )
    return report


def main() -> None:
    oof, targets, sessions = _load_inputs()
    events = [*FEATURE_CONDITIONAL_EVENTS, *BASE_RATE_ONLY_EVENTS]
    result = {
        "status": "P0_COMPLETE_RECOMMENDATION_ONLY_NOT_FROZEN",
        "scope": {
            "weather_station_only": True,
            "product_prices_read": False,
            "economic_probe_read": False,
            "model_or_config_modified": False,
            "files_written": False,
        },
        "inputs": {
            "oof": _artifact_identity(OOF_PATH),
            "targets": _artifact_identity(TARGET_PATH),
            "calendar": _artifact_identity(CALENDAR_PATH),
            "oof_rows": len(oof),
            "target_rows": len(targets),
            "calendar_sessions": len(sessions),
        },
        "method": {
            "primary_block_sessions": PRIMARY_BLOCK_SESSIONS,
            "block_sensitivity": BLOCK_SENSITIVITY,
            "bootstrap_replications": BOOTSTRAP_REPLICATIONS,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "power_alpha_one_sided": 0.05,
            "power_target": 0.80,
            "power_skill_sensitivity": SKILL_SENSITIVITY,
            "positive_episode_close_after_no_positive_sessions": "event_horizon",
            "negative_blocks": "nonoverlapping event-horizon session blocks",
        },
        "recommended_evidence_floor": EVIDENCE_FLOOR,
        "events": {
            event: _event_report(oof, sessions, event, number)
            for number, event in enumerate(events)
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
