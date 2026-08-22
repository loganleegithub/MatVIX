from __future__ import annotations

from typing import Any, TypeAlias, cast

import numpy as np
import pandas as pd

Tri: TypeAlias = bool | None

MID_PRICED_PERCENTILE = 0.75
MID_PRICED_INVERSION_SHARE = 2.0 / 3.0
MID_PRIOR_PRICED_WINDOW = 10
BROAD_PRESSURE_WINDOW = 5
BROAD_PRESSURE_REQUIRED = 3
RECENT_STRESS_WINDOW = 10
REPAIR_BUILDING_SCORE = 60.0


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
    priced_days: list[Tri] = []
    rising_days: list[Tri] = []
    for row in result.itertuples(index=False):
        priced_days.append(
            tri_or(
                _compare(row.p_f4_f7_level, ">=", MID_PRICED_PERCENTILE),
                _compare(
                    row.f4_f7_inversion_share,
                    ">=",
                    MID_PRICED_INVERSION_SHARE,
                ),
            )
        )
        rising_days.append(
            tri_and(
                _compare(row.d5_log_f4_f7_level, ">", 0.0),
                tri_or(
                    _compare(row.d5_f4_f7_slope30, "<", 0.0),
                    _compare(row.d5_f4_f7_inversion_share, ">", 0.0),
                ),
            )
        )

    mid_states: list[str] = []
    for index in range(len(result)):
        prior = priced_days[max(0, index - MID_PRIOR_PRICED_WINDOW) : index]
        prior_padding: list[Tri] = [None] * (MID_PRIOR_PRICED_WINDOW - len(prior))
        prior = prior_padding + prior
        receding = tri_and(
            any_true(prior),
            _compare(result.iloc[index]["d5_log_f4_f7_level"], "<", 0.0),
            tri_or(
                _compare(result.iloc[index]["d5_f4_f7_slope30"], ">", 0.0),
                _compare(result.iloc[index]["d5_f4_f7_inversion_share"], "<", 0.0),
            ),
        )
        priced, rising = priced_days[index], rising_days[index]
        if receding is True:
            mid_states.append("RECEDING")
        elif receding is None:
            mid_states.append("UNKNOWN")
        elif priced is True:
            mid_states.append("PRICED")
        elif priced is None:
            mid_states.append("UNKNOWN")
        elif rising is True:
            mid_states.append("RISING")
        elif rising is None:
            mid_states.append("UNKNOWN")
        else:
            mid_states.append("QUIET")
    result["mid_curve_pressure_state"] = mid_states

    front_pressure: list[Tri] = []
    scopes: list[str] = []
    carry_open_days: list[Tri] = []
    carry_states: list[str] = []
    for index, row in result.iterrows():
        front = tri_or(
            _compare(row["near_stress_log_ratio"], ">", 0.0),
            _compare(row["front_slope30"], "<", 0.0),
        )
        front_pressure.append(front)
        mid = mid_states[index]
        if front is None or mid == "UNKNOWN":
            scope = "UNKNOWN"
        elif front and mid in {"RISING", "PRICED"}:
            scope = "BROAD"
        elif not front and mid in {"RISING", "PRICED"}:
            scope = "MID"
        elif front:
            scope = "FRONT"
        else:
            scope = "NONE"
        scopes.append(scope)

        open_day = tri_and(
            _compare(row["front_slope30"], ">", 0.0),
            _compare(row["basis30_eod"], ">", 0.0),
            _compare(row["near_stress_log_ratio"], "<=", 0.0),
            _compare(row["f4_f7_slope30"], ">", 0.0),
            None if mid == "UNKNOWN" else mid == "QUIET",
        )
        carry_open_days.append(open_day)
        previous_open = carry_open_days[index - 1] if index else None
        if open_day is None:
            carry_states.append("UNKNOWN")
        elif open_day is True and previous_open is True:
            carry_states.append("OPEN")
        elif open_day is True or mid == "RECEDING":
            carry_states.append("RECOVERING")
        else:
            carry_states.append("CLOSED")
    result["front_pressure"] = pd.Series(front_pressure, dtype="object")
    result["stress_tenor_scope"] = scopes
    result["carry_open_day"] = pd.Series(carry_open_days, dtype="object")
    result["carry_environment_state"] = carry_states

    broad_days: list[Tri] = []
    stress_days: list[Tri] = []
    for index in range(len(result)):
        scope, mid = scopes[index], mid_states[index]
        broad_days.append(None if scope == "UNKNOWN" else scope == "BROAD" and mid in {"RISING", "PRICED"})
        scope_stress = None if scope == "UNKNOWN" else scope != "NONE"
        stress_days.append(tri_or(scope_stress, _tri(result.iloc[index]["hard_acute"])))

    broad_now: list[Tri] = []
    recent_stress: list[Tri] = []
    for index in range(len(result)):
        broad_window = broad_days[max(0, index - BROAD_PRESSURE_WINDOW + 1) : index + 1]
        broad_padding: list[Tri] = [None] * (BROAD_PRESSURE_WINDOW - len(broad_window))
        broad_window = broad_padding + broad_window
        broad_now.append(at_least_k_true(broad_window, BROAD_PRESSURE_REQUIRED))
        stress_window = stress_days[max(0, index - RECENT_STRESS_WINDOW + 1) : index + 1]
        stress_padding: list[Tri] = [None] * (RECENT_STRESS_WINDOW - len(stress_window))
        stress_window = stress_padding + stress_window
        recent_stress.append(any_true(stress_window))
    result["broad_pressure_day"] = pd.Series(broad_days, dtype="object")
    result["broad_pressure_now"] = pd.Series(broad_now, dtype="object")
    result["recent_stress"] = pd.Series(recent_stress, dtype="object")
    result["repair_confirmed"] = pd.Series(
        [None if value == "UNKNOWN" else value == "RECEDING" for value in mid_states],
        dtype="object",
    )

    formal_chain = (
        result.get(
            "formal_chain_admitted",
            result.get("formal_vintage_eligible", pd.Series(False, index=result.index)),
        )
        .fillna(False)
        .astype(bool)
    )
    result["hard_acute_formal_vintage_eligible"] = formal_chain & result["hard_acute"].notna()
    result["mid_curve_formal_vintage_eligible"] = formal_chain & result[
        "mid_curve_pressure_state"
    ].ne("UNKNOWN")
    result["broad_pressure_day_formal_vintage_eligible"] = (
        formal_chain & result["broad_pressure_day"].notna()
    )
    result["carry_environment_formal_vintage_eligible"] = formal_chain & result[
        "carry_environment_state"
    ].ne("UNKNOWN")
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
        carry_state = carry_states[index]
        if carry_state == "UNKNOWN" or pd.isna(row["front_slope30"]):
            carry = "UNKNOWN"
        elif carry_state == "OPEN":
            carry = "SUPPORTIVE"
        elif float(row["front_slope30"]) < 0:
            carry = "INVERTED"
        elif carry_state == "CLOSED":
            carry = "STRESSED"
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

        p_now = broad_now[index]
        scope, mid = scopes[index], mid_states[index]
        if p_now is None or scope == "UNKNOWN" or mid == "UNKNOWN":
            persistence = "UNKNOWN"
        elif p_now is True:
            persistence = "PERSISTENT"
        elif scope == "BROAD" and mid == "RISING":
            persistence = "DIFFUSING"
        elif scope == "FRONT":
            persistence = "FRONT_LOCALIZED"
        elif scope == "NONE" and mid == "QUIET":
            persistence = "NORMAL"
        else:
            persistence = "MIXED"
        persistence_answers.append(persistence)

        r_confirmed = _tri(result.iloc[index]["repair_confirmed"])
        r_stress = recent_stress[index]
        repair_building = tri_and(
            r_stress,
            _compare(row["repair_score"], ">=", REPAIR_BUILDING_SCORE),
        )
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

        if (
            row["data_status"] != "OK"
            or carry == "UNKNOWN"
            or persistence == "UNKNOWN"
            or repair == "UNKNOWN"
            or shock == "UNKNOWN"
            or tail == "UNKNOWN"
        ):
            raw_phase = "UNKNOWN"
        elif _tri(row["hard_acute"]) is True:
            raw_phase = "ACUTE_FRONT_STRESS"
        elif persistence == "PERSISTENT":
            raw_phase = "BROAD_PERSISTENT_STRESS"
        elif persistence == "DIFFUSING":
            raw_phase = "PRESSURE_DIFFUSING"
        elif repair == "CONFIRMED":
            raw_phase = "REPAIR_IN_PROGRESS"
        elif persistence == "FRONT_LOCALIZED":
            raw_phase = "FRONT_LOCALIZED_STRESS"
        elif (
            carry == "SUPPORTIVE"
            and shock == "CALM"
            and persistence == "NORMAL"
            and tail in {"RICH", "EXTREME"}
        ):
            raw_phase = "TAIL_RICH_QUIET_CURVE"
        elif carry == "SUPPORTIVE" and shock == "CALM" and persistence == "NORMAL":
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
