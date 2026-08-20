from __future__ import annotations

from typing import Any, TypeAlias, cast

import numpy as np
import pandas as pd

Tri: TypeAlias = bool | None


def _tri(value: object) -> Tri:
    if value is None or pd.isna(value):
        return None
    return bool(value)


def tri_and(*values: Tri) -> Tri:
    if any(value is False for value in values):
        return False
    if all(value is True for value in values):
        return True
    return None


def tri_or(*values: Tri) -> Tri:
    if any(value is True for value in values):
        return True
    if all(value is False for value in values):
        return False
    return None


def at_least_k_true(values: list[Tri], k: int) -> Tri:
    true_count = sum(value is True for value in values)
    unknown_count = sum(value is None for value in values)
    if true_count >= k:
        return True
    if true_count + unknown_count < k:
        return False
    return None


def any_true(values: list[Tri]) -> Tri:
    return tri_or(*values)


def _compare(value: object, operator: str, threshold: float) -> Tri:
    if value is None or pd.isna(value):
        return None
    numeric = float(cast(Any, value))
    if operator == ">=":
        return numeric >= threshold
    if operator == ">":
        return numeric > threshold
    if operator == "<":
        return numeric < threshold
    if operator == "<=":
        return numeric <= threshold
    raise ValueError(operator)


def _eq_false(value: object) -> Tri:
    tri = _tri(value)
    return None if tri is None else not tri


def add_state_predicates_and_answers(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    persistent_days: list[Tri] = []
    stress_days: list[Tri] = []
    for row in result.itertuples(index=False):
        persistent_days.append(
            tri_and(
                _compare(row.persistence_score, ">=", 75.0),
                _compare(row.baseline_score, ">=", 65.0),
            )
        )
        stress_days.append(
            tri_or(
                _compare(row.baseline_score, ">=", 70.0),
                _tri(row.hard_acute),
            )
        )
    result["persistent_day"] = pd.Series(persistent_days, dtype="object")
    result["stress_day"] = pd.Series(stress_days, dtype="object")

    persistent_now: list[Tri] = []
    recent_stress: list[Tri] = []
    for index in range(len(result)):
        p_start = max(0, index - 4)
        p_window = persistent_days[p_start : index + 1]
        # A full five-session window is required; unavailable prehistory is UNKNOWN.
        if len(p_window) < 5:
            p_padding: list[Tri] = [None] * (5 - len(p_window))
            p_window = p_padding + p_window
        persistent_now.append(at_least_k_true(p_window, 3))

        s_start = max(0, index - 9)
        s_window = stress_days[s_start : index + 1]
        if len(s_window) < 10:
            s_padding: list[Tri] = [None] * (10 - len(s_window))
            s_window = s_padding + s_window
        recent_stress.append(any_true(s_window))
    result["persistent_now"] = pd.Series(persistent_now, dtype="object")
    result["recent_stress"] = pd.Series(recent_stress, dtype="object")

    repair_confirmed: list[Tri] = []
    for index, row in result.iterrows():
        previous = result.iloc[index - 1] if index > 0 else None
        previous_repair = None if previous is None else _compare(previous["repair_score"], ">=", 70)
        shock_falling = (
            None
            if previous is None or pd.isna(row["shock_score"]) or pd.isna(previous["shock_score"])
            else float(row["shock_score"]) < float(previous["shock_score"])
        )
        repair_confirmed.append(
            tri_and(
                recent_stress[index],
                _compare(row["repair_score"], ">=", 70),
                previous_repair,
                shock_falling,
                _compare(row["p_d5_fvol_30_93"], "<", 0.60),
                _eq_false(row["hard_acute"]),
            )
        )
    result["repair_confirmed"] = pd.Series(repair_confirmed, dtype="object")
    formal_chain = (
        result.get("formal_chain_admitted", pd.Series(False, index=result.index))
        .fillna(False)
        .astype(bool)
    )
    result["hard_acute_formal_vintage_eligible"] = formal_chain & result["hard_acute"].notna()
    result["persistent_day_formal_vintage_eligible"] = (
        formal_chain & result["persistent_day"].notna()
    )
    result["repair_confirmed_formal_vintage_eligible"] = (
        formal_chain & result["repair_confirmed"].notna()
    )

    carry_answers: list[str] = []
    shock_answers: list[str] = []
    tail_answers: list[str] = []
    persistence_answers: list[str] = []
    repair_answers: list[str] = []
    raw_phases: list[str] = []

    for index, row in result.iterrows():
        if (
            pd.isna(row["carry_risk_score"])
            or pd.isna(row["front_slope30"])
            or pd.isna(row["basis30_eod"])
        ):
            carry = "UNKNOWN"
        elif float(row["front_slope30"]) < 0:
            carry = "INVERTED"
        elif float(row["carry_risk_score"]) >= 65:
            carry = "STRESSED"
        elif (
            float(row["carry_risk_score"]) < 35
            and float(row["front_slope30"]) > 0
            and float(row["basis30_eod"]) > 0
        ):
            carry = "SUPPORTIVE"
        else:
            carry = "MIXED"
        carry_answers.append(carry)

        if pd.isna(row["shock_score"]) or pd.isna(row["front_confirmation_count"]):
            shock = "UNKNOWN"
        elif float(row["shock_score"]) >= 85 and float(row["front_confirmation_count"]) >= 2:
            shock = "ACUTE"
        elif float(row["shock_score"]) >= 65:
            shock = "HIGH"
        elif float(row["shock_score"]) >= 40:
            shock = "BUILDING"
        else:
            shock = "CALM"
        shock_answers.append(shock)

        if pd.isna(row["tail_price_score"]):
            tail = "UNKNOWN"
        elif float(row["tail_price_score"]) >= 90:
            tail = "EXTREME"
        elif float(row["tail_price_score"]) >= 75:
            tail = "RICH"
        elif float(row["tail_price_score"]) >= 60:
            tail = "ELEVATED"
        else:
            tail = "NORMAL"
        tail_answers.append(tail)

        p_now = persistent_now[index]
        if pd.isna(row["persistence_score"]) or pd.isna(row["shock_score"]) or p_now is None:
            persistence = "UNKNOWN"
        elif p_now is True:
            persistence = "PERSISTENT"
        elif (
            float(row["persistence_score"]) >= 55
            and float(row["d5_fvol_30_93"]) > 0
            and float(row["p_d5_fvol_30_93"]) >= 0.70
        ):
            persistence = "DIFFUSING"
        elif float(row["shock_score"]) >= 65 and float(row["persistence_score"]) < 50:
            persistence = "FRONT_LOCALIZED"
        elif float(row["persistence_score"]) < 55 and float(row["shock_score"]) < 65:
            persistence = "NORMAL"
        else:
            persistence = "MIXED"
        persistence_answers.append(persistence)

        r_confirmed = repair_confirmed[index]
        r_stress = recent_stress[index]
        repair_building = tri_and(r_stress, _compare(row["repair_score"], ">=", 60))
        if pd.isna(row["repair_score"]):
            repair = "UNKNOWN"
        elif r_confirmed is True:
            repair = "CONFIRMED"
        elif r_confirmed is None:
            repair = "UNKNOWN"
        elif repair_building is True:
            repair = "BUILDING"
        elif repair_building is None:
            repair = "UNKNOWN"
        else:
            repair = "INACTIVE"
        repair_answers.append(repair)

        if row["data_status"] != "OK":
            raw_phase = "UNKNOWN"
        elif _tri(row["hard_acute"]) is True:
            raw_phase = "ACUTE_FRONT_STRESS"
        elif repair == "CONFIRMED":
            raw_phase = "REPAIR_IN_PROGRESS"
        elif p_now is True:
            raw_phase = "BROAD_PERSISTENT_STRESS"
        # Calendar-localized premium is disabled without an admitted event calendar.
        elif float(row["shock_score"]) >= 60 and float(row["baseline_score"]) >= 60:
            raw_phase = "PRESSURE_BUILDING"
        elif (
            float(row["carry_risk_score"]) < 45
            and float(row["shock_score"]) < 55
            and float(row["persistence_score"]) < 55
            and float(row["tail_price_score"]) >= 75
        ):
            raw_phase = "TAIL_RICH_QUIET_CURVE"
        elif (
            float(row["carry_risk_score"]) < 35
            and float(row["shock_score"]) < 40
            and float(row["persistence_score"]) < 45
            and float(row["tail_price_score"]) < 65
        ):
            raw_phase = "CARRY_SUPPORTIVE_LOW_STRESS"
        else:
            raw_phase = "MIXED_TRANSITION"
        raw_phases.append(raw_phase)

    result["carry_answer"] = carry_answers
    result["shock_answer"] = shock_answers
    result["tail_answer"] = tail_answers
    result["persistence_answer"] = persistence_answers
    result["repair_answer"] = repair_answers
    result["raw_phase"] = raw_phases

    answer_columns = [
        "carry_answer",
        "shock_answer",
        "tail_answer",
        "persistence_answer",
        "repair_answer",
    ]
    indeterminate_current_state = result[answer_columns].eq("UNKNOWN").any(axis=1)
    downgrade = result["data_status"].eq("OK") & indeterminate_current_state
    result.loc[downgrade, "data_status"] = "PARTIAL"
    for column in ("baseline_score", "d5_baseline_score"):
        if column in result:
            result.loc[downgrade, column] = np.nan
    for column in ("pressure_level", "direction"):
        if column in result:
            result.loc[downgrade, column] = "UNKNOWN"

    non_ok = result["data_status"].ne("OK")
    result.loc[
        non_ok,
        [
            "carry_answer",
            "shock_answer",
            "tail_answer",
            "persistence_answer",
            "repair_answer",
            "raw_phase",
        ],
    ] = "UNKNOWN"
    return result
