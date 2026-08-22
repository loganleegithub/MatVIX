from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from matvix.features.percentile import rolling_midrank_percentile

PERCENTILE_INPUTS: Mapping[str, tuple[str, int]] = {
    # output column -> (source column, sign)
    "p_neg_front_slope30": ("front_slope30", -1),
    "p_neg_basis30_eod": ("basis30_eod", -1),
    "p_neg_d5_front_slope30": ("d5_front_slope30", -1),
    "p_near_stress": ("near_stress_log_ratio", 1),
    "p_d1_log_vix": ("d1_log_vix", 1),
    "p_d5_log_vix": ("d5_log_vix", 1),
    "p_d5_log_vvix": ("d5_log_vvix", 1),
    "p_vvix": ("vvix_close", 1),
    "p_skew": ("skew_close", 1),
    "p_d5_skew": ("d5_skew", 1),
    "p_fvol_30_93": ("fvol_30_93", 1),
    "p_fvol_93_184": ("fvol_93_184", 1),
    "p_d5_fvol_30_93": ("d5_fvol_30_93", 1),
    "p_neg_d5_log_vix": ("d5_log_vix", -1),
    "p_neg_d5_near_stress": ("d5_near_stress", -1),
    "p_d5_front_slope30": ("d5_front_slope30", 1),
    "p_neg_d5_log_vvix": ("d5_log_vvix", -1),
    "p_neg_d5_fvol_30_93": ("d5_fvol_30_93", -1),
    "p_f4_f7_level": ("f4_f7_level", 1),
    "p_neg_f4_f7_slope30": ("f4_f7_slope30", -1),
    "p_d5_log_f4_f7_level": ("d5_log_f4_f7_level", 1),
    "p_neg_d5_log_f4_f7_level": ("d5_log_f4_f7_level", -1),
    "p_d5_f4_f7_slope30": ("d5_f4_f7_slope30", 1),
    "p_neg_d5_f4_f7_slope30": ("d5_f4_f7_slope30", -1),
    "p_cash_vix_oscillator": ("cash_vix_oscillator", 1),
    "p_vrp_ewma94": ("vrp_ewma94", 1),
}

AXIS_COMPONENTS: dict[str, list[tuple[str, str, float, str]]] = {
    "carry_risk": [
        ("carry.front_slope", "p_neg_front_slope30", 0.45, "front_slope30"),
        ("carry.basis30_eod", "p_neg_basis30_eod", 0.35, "basis30_eod"),
        (
            "carry.slope_change_5d",
            "p_neg_d5_front_slope30",
            0.20,
            "d5_front_slope30",
        ),
    ],
    "shock": [
        ("shock.near_stress", "p_near_stress", 0.30, "near_stress_log_ratio"),
        ("shock.vix_change_1d", "p_d1_log_vix", 0.20, "d1_log_vix"),
        ("shock.vix_change_5d", "p_d5_log_vix", 0.20, "d5_log_vix"),
        ("shock.vvix_change_5d", "p_d5_log_vvix", 0.15, "d5_log_vvix"),
        ("shock.vvix_level", "p_vvix", 0.15, "vvix_close"),
    ],
    "tail_price": [
        ("tail.skew_level", "p_skew", 0.70, "skew_close"),
        ("tail.skew_change_5d", "p_d5_skew", 0.30, "d5_skew"),
    ],
    "persistence": [
        ("persistence.f4_f7_level", "p_f4_f7_level", 0.40, "f4_f7_level"),
        (
            "persistence.f4_f7_slope30",
            "p_neg_f4_f7_slope30",
            0.30,
            "f4_f7_slope30",
        ),
        (
            "persistence.f4_f7_level_change_5d",
            "p_d5_log_f4_f7_level",
            0.20,
            "d5_log_f4_f7_level",
        ),
        (
            "persistence.f4_f7_inversion_breadth",
            "f4_f7_inversion_share",
            0.10,
            "f4_f7_inversion_share",
        ),
    ],
    "repair": [
        ("repair.vix", "p_neg_d5_log_vix", 0.30, "d5_log_vix"),
        (
            "repair.near_stress",
            "p_neg_d5_near_stress",
            0.25,
            "d5_near_stress",
        ),
        (
            "repair.front_slope",
            "p_d5_front_slope30",
            0.20,
            "d5_front_slope30",
        ),
        ("repair.vvix", "p_neg_d5_log_vvix", 0.15, "d5_log_vvix"),
        (
            "repair.f4_f7_level",
            "p_neg_d5_log_f4_f7_level",
            0.10,
            "d5_log_f4_f7_level",
        ),
    ],
}

AXIS_BASELINE_WEIGHTS = {
    "carry_risk": 0.30,
    "shock": 0.30,
    "tail_price": 0.20,
    "persistence": 0.20,
}


def _rolling_percentile_for_methodology(
    series: pd.Series,
    signatures: pd.Series,
    *,
    reference_sessions: int,
    minimum_valid: int,
) -> pd.Series:
    """Keep each PIT percentile inside the current feature methodology."""
    normalized = signatures.astype("string")
    result = pd.Series(np.nan, index=series.index, dtype=float)
    for signature in normalized.dropna().unique():
        same_methodology = normalized.eq(signature).fillna(False)
        isolated = rolling_midrank_percentile(
            series.where(same_methodology),
            reference_sessions=reference_sessions,
            minimum_valid=minimum_valid,
        )
        result.loc[same_methodology] = isolated.loc[same_methodology]
    return result


def _weighted_score(
    frame: pd.DataFrame, components: list[tuple[str, str, float, str]]
) -> pd.Series:
    values = pd.DataFrame(index=frame.index)
    for _, percentile_column, weight, _ in components:
        values[percentile_column] = (
            pd.to_numeric(frame[percentile_column], errors="coerce") * weight
        )
    # A missing component invalidates the entire fixed-weight axis; no re-normalization.
    complete = frame[[component[1] for component in components]].notna().all(axis=1)
    result = 100.0 * values.sum(axis=1, min_count=len(components))
    return result.where(complete)


def add_percentiles_and_scores(
    features: pd.DataFrame,
    *,
    reference_sessions: int = 756,
    minimum_valid: int = 504,
) -> pd.DataFrame:
    frame = features.copy()
    for output, (source, sign) in PERCENTILE_INPUTS.items():
        transformed = sign * pd.to_numeric(frame[source], errors="coerce")
        transformed.name = source
        if "feature_methodology_signature" in frame:
            frame[output] = _rolling_percentile_for_methodology(
                transformed,
                frame["feature_methodology_signature"],
                reference_sessions=reference_sessions,
                minimum_valid=minimum_valid,
            )
        else:
            # Backward-compatible for callers that predate the signature field.
            # Once the field is present, a missing row signature is deliberately
            # left unscored rather than borrowing another methodology's history.
            frame[output] = rolling_midrank_percentile(
                transformed,
                reference_sessions=reference_sessions,
                minimum_valid=minimum_valid,
            )

    frame["carry_risk_score"] = _weighted_score(frame, AXIS_COMPONENTS["carry_risk"])
    frame["shock_score"] = _weighted_score(frame, AXIS_COMPONENTS["shock"])
    frame["tail_price_score"] = _weighted_score(frame, AXIS_COMPONENTS["tail_price"])
    frame["persistence_score"] = _weighted_score(frame, AXIS_COMPONENTS["persistence"])
    frame["repair_score"] = _weighted_score(frame, AXIS_COMPONENTS["repair"])

    required_axes = [f"{axis}_score" for axis in AXIS_BASELINE_WEIGHTS]
    complete = frame[required_axes].notna().all(axis=1)
    frame["baseline_score"] = sum(
        frame[f"{axis}_score"] * weight for axis, weight in AXIS_BASELINE_WEIGHTS.items()
    ).where(complete)
    frame["d5_baseline_score"] = frame["baseline_score"] - frame["baseline_score"].shift(5)

    frame["vrp_percentile"] = frame["p_vrp_ewma94"]
    frame["carry_compensation"] = np.select(
        [frame["vrp_percentile"] < 0.35, frame["vrp_percentile"] >= 0.75],
        ["THIN", "RICH"],
        default="NORMAL",
    )
    frame.loc[frame["vrp_percentile"].isna(), "carry_compensation"] = "UNKNOWN"

    f1 = frame["vx_settles"].map(
        lambda values: values[0] if isinstance(values, list) and values else np.nan
    )
    f2 = frame["vx_settles"].map(
        lambda values: values[1] if isinstance(values, list) and len(values) > 1 else np.nan
    )
    confirmations = pd.DataFrame(
        {
            "vix9d_gt_vix": frame["vix9d_close"] > frame["vix_close"],
            "f1_gt_f2": f1 > f2,
            "cash_osc_extreme": frame["p_cash_vix_oscillator"] >= 0.90,
        }
    )
    confirmation_observable = pd.DataFrame(
        {
            "vix9d_gt_vix": frame[["vix9d_close", "vix_close"]].notna().all(axis=1),
            "f1_gt_f2": f1.notna() & f2.notna(),
            "cash_osc_extreme": frame["p_cash_vix_oscillator"].notna(),
        }
    ).all(axis=1)
    frame["front_confirmation_count"] = confirmations.sum(axis=1).where(confirmation_observable)
    frame["hard_acute"] = (
        (frame["shock_score"] >= 85.0) & (frame["front_confirmation_count"] >= 2)
    ).where(frame[["shock_score", "front_confirmation_count"]].notna().all(axis=1))

    core_foundation = frame[["vix_close", "vxcm30"]].notna().all(axis=1)
    all_scores = (
        frame[
            [
                "carry_risk_score",
                "shock_score",
                "tail_price_score",
                "persistence_score",
                "repair_score",
                "baseline_score",
            ]
        ]
        .notna()
        .all(axis=1)
    )
    formal = frame["formal_vintage_eligible"].fillna(False)
    frame["data_status"] = np.where(
        ~core_foundation,
        "UNKNOWN",
        np.where(all_scores & formal, "OK", "PARTIAL"),
    )
    frame.loc[frame["data_status"] != "OK", ["baseline_score", "d5_baseline_score"]] = np.nan
    frame["pressure_level"] = pd.cut(
        frame["baseline_score"],
        bins=[-np.inf, 35, 55, 70, 85, np.inf],
        labels=["LOW", "WATCH", "ELEVATED", "HIGH", "EXTREME"],
        right=False,
    ).astype(object)
    frame.loc[frame["baseline_score"].isna(), "pressure_level"] = "UNKNOWN"
    frame["direction"] = np.select(
        [frame["d5_baseline_score"] >= 7.5, frame["d5_baseline_score"] <= -7.5],
        ["RISING", "FALLING"],
        default="STABLE",
    )
    frame.loc[frame["d5_baseline_score"].isna(), "direction"] = "UNKNOWN"
    return frame


def component_contributions(row: pd.Series) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for axis, components in AXIS_COMPONENTS.items():
        if axis == "repair":
            continue
        axis_weight = AXIS_BASELINE_WEIGHTS[axis]
        for evidence_id, percentile_column, within_weight, raw_feature in components:
            percentile = row.get(percentile_column)
            raw_value = row.get(raw_feature)
            if percentile is None or pd.isna(percentile):
                continue
            records.append(
                {
                    "id": evidence_id,
                    "axis": axis,
                    "percentile": float(percentile),
                    "raw_value": None if pd.isna(raw_value) else float(raw_value),
                    "contribution": float(axis_weight * within_weight * (float(percentile) - 0.5)),
                    "feature_refs": [raw_feature, percentile_column],
                }
            )
    return records


def repair_components(row: pd.Series) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for evidence_id, percentile_column, within_weight, raw_feature in AXIS_COMPONENTS["repair"]:
        percentile = row.get(percentile_column)
        raw_value = row.get(raw_feature)
        if percentile is None or pd.isna(percentile):
            continue
        records.append(
            {
                "id": evidence_id,
                "percentile": float(percentile),
                "raw_value": None if pd.isna(raw_value) else float(raw_value),
                "contribution": float(within_weight * (float(percentile) - 0.5)),
                "feature_refs": [raw_feature, percentile_column],
            }
        )
    return records


def add_probability_predictors(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["carry_risk_scaled"] = result["carry_risk_score"] / 100.0
    result["shock_scaled"] = result["shock_score"] / 100.0
    result["tail_price_scaled"] = result["tail_price_score"] / 100.0
    result["persistence_scaled"] = result["persistence_score"] / 100.0
    result["repair_scaled"] = result["repair_score"] / 100.0
    result["score_change5_scaled"] = ((result["d5_baseline_score"] + 100.0) / 200.0).clip(0, 1)
    result["inverse_score_change5_scaled"] = 1.0 - result["score_change5_scaled"]
    result["front_confirmation_scaled"] = result["front_confirmation_count"] / 3.0
    return result
