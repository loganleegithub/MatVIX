from __future__ import annotations

from typing import TypeAlias

import numpy as np
import pandas as pd

from matvix.calendar import add_sessions, decision_as_of
from matvix.constants import (
    CARRY_DURATION_FACTS,
    EVENT_HORIZONS,
    EVENT_ORDER,
    LOGISTIC_FEATURES,
)

Tri: TypeAlias = bool | None


def _known_bool(value: object) -> Tri:
    if value is None or pd.isna(value):
        return None
    return bool(value)


def _event_onset(row: pd.Series, event: str) -> Tri:
    if event == "acute_front_stress_5d":
        hard = _known_bool(row.get("hard_acute"))
        return None if hard is None else not hard
    if event == "front_inversion_5d":
        value = row.get("front_slope30")
        return None if value is None or pd.isna(value) else float(value) >= 0.0
    if event == "mid_curve_pressure_accelerates_5d":
        state = row.get("mid_curve_pressure_state")
        if state in (None, "UNKNOWN") or pd.isna(state):
            return None
        return str(state) in {"QUIET", "RECEDING"}
    if event == "broad_stress_persists_10d":
        return _known_bool(row.get("broad_pressure_day"))
    if event == "carry_environment_recovers_10d":
        carry = row.get("carry_environment_state")
        if carry in (None, "UNKNOWN") or pd.isna(carry):
            return None
        if carry not in {"CLOSED", "RECOVERING"}:
            return False
        front = _known_bool(row.get("front_pressure"))
        mid = row.get("mid_curve_pressure_state")
        mid_pressure = None if mid in (None, "UNKNOWN") or pd.isna(mid) else mid != "QUIET"
        if front is True or mid_pressure is True:
            return True
        if front is False and mid_pressure is False:
            return False
        return None
    raise KeyError(event)


def global_model_observable(row: pd.Series, event: str) -> bool:
    if row.get("data_status") != "OK":
        return False
    if not bool(row.get("formal_vintage_eligible", False)):
        return False
    required_features = (
        [feature for feature in LOGISTIC_FEATURES[event] if feature not in CARRY_DURATION_FACTS]
        if event == "carry_environment_recovers_10d"
        else LOGISTIC_FEATURES[event]
    )
    return all(
        feature in row.index and row.get(feature) is not None and not pd.isna(row.get(feature))
        for feature in required_features
    )


def event_status(row: pd.Series, event: str) -> str:
    if not global_model_observable(row, event):
        return "UNOBSERVABLE"
    onset = _event_onset(row, event)
    if onset is None:
        return "UNOBSERVABLE"
    return "ELIGIBLE" if onset else "NOT_APPLICABLE"


def add_event_statuses(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for event in EVENT_ORDER:
        result[f"{event}__event_status"] = [
            event_status(row, event) for _, row in result.iterrows()
        ]
        result[f"{event}__onset"] = [_event_onset(row, event) for _, row in result.iterrows()]
    return result


def add_carry_duration_facts(frame: pd.DataFrame) -> pd.DataFrame:
    """Add causal Carry spell age without bridging non-eligible rows or session gaps."""

    if "session_date" not in frame:
        raise ValueError("Carry duration facts require session_date")
    result = frame.copy()
    dates = pd.to_datetime(result["session_date"], errors="coerce").dt.normalize()
    if dates.isna().any():
        raise ValueError("Carry duration facts contain an invalid session_date")

    ages = pd.Series(np.nan, index=result.index, dtype=float)
    recovering = pd.Series(np.nan, index=result.index, dtype=float)
    prior_date: pd.Timestamp | None = None
    prior_eligible = False
    prior_age = 0
    for index in dates.sort_values(kind="stable").index:
        row = result.loc[index]
        current_date = pd.Timestamp(dates.loc[index]).normalize()
        contiguous = prior_date is not None and current_date == add_sessions(prior_date, 1)
        status = event_status(row, "carry_environment_recovers_10d")
        if status == "ELIGIBLE":
            age = prior_age + 1 if contiguous and prior_eligible else 1
            ages.loc[index] = float(age)
            recovering.loc[index] = float(row.get("carry_environment_state") == "RECOVERING")
            prior_age = age
            prior_eligible = True
        else:
            prior_age = 0
            prior_eligible = False
        prior_date = current_date

    result["carry_spell_age"] = ages
    result["log1p_carry_spell_age"] = np.log1p(ages)
    result["carry_recovering_flag"] = recovering
    return result


def _future_predicate(row: pd.Series, event: str) -> Tri:
    if event == "acute_front_stress_5d":
        return _known_bool(row.get("hard_acute"))
    if event == "front_inversion_5d":
        value = row.get("front_slope30")
        return None if value is None or pd.isna(value) else float(value) < 0.0
    if event == "mid_curve_pressure_accelerates_5d":
        state = row.get("mid_curve_pressure_state")
        return None if state in (None, "UNKNOWN") or pd.isna(state) else state == "RISING"
    if event == "broad_stress_persists_10d":
        return _known_bool(row.get("broad_pressure_day"))
    if event == "carry_environment_recovers_10d":
        state = row.get("carry_environment_state")
        return None if state in (None, "UNKNOWN") or pd.isna(state) else state == "OPEN"
    raise KeyError(event)


def _future_predicate_vintage_eligible(row: pd.Series, event: str) -> bool:
    """Return the formal-vintage gate for the outcome's own input chain.

    Front inversion depends only on the front futures curve.  Other event
    predicates currently inherit the complete state-chain gate because their
    published booleans combine multiple scores.  The explicit front flag lets
    an unrelated index gap remain irrelevant without weakening PIT evidence.
    """

    predicate_flags = {
        "acute_front_stress_5d": "hard_acute_formal_vintage_eligible",
        "front_inversion_5d": "front_curve_formal_vintage_eligible",
        "mid_curve_pressure_accelerates_5d": "mid_curve_formal_vintage_eligible",
        "broad_stress_persists_10d": "broad_pressure_day_formal_vintage_eligible",
        "carry_environment_recovers_10d": "carry_environment_formal_vintage_eligible",
    }
    flag = predicate_flags[event]
    if flag in row.index:
        value = row.get(flag)
        return value is not None and not pd.isna(value) and bool(value)
    return bool(row.get("formal_vintage_eligible", False))


def build_target_ledger(frame: pd.DataFrame) -> pd.DataFrame:
    """Build event-specific PIT labels with explicit censoring.

    Positive outcomes remain unavailable until the complete horizon closes, even
    if the event triggers early.
    """

    state = add_event_statuses(add_carry_duration_facts(frame)).reset_index(drop=True)
    records: list[dict[str, object]] = []
    for index, row in state.iterrows():
        prediction_date = pd.Timestamp(row["session_date"]).normalize()
        for event in EVENT_ORDER:
            horizon = EVENT_HORIZONS[event]
            current_status = str(row[f"{event}__event_status"])
            record: dict[str, object] = {
                "event_id": event,
                "prediction_date": prediction_date,
                "event_status": current_status,
                "label": np.nan,
                "label_status": "CENSORED",
                "horizon_sessions": horizon,
                "valid_through_session": pd.NaT,
                "outcome_available_at": pd.NaT,
                "formal_vintage_eligible": bool(row.get("formal_vintage_eligible", False)),
            }
            if current_status == "NOT_APPLICABLE":
                record["label_status"] = "NOT_APPLICABLE"
                records.append(record)
                continue
            if current_status != "ELIGIBLE":
                records.append(record)
                continue
            end = index + horizon
            if end >= len(state):
                records.append(record)
                continue
            future = state.iloc[index + 1 : end + 1]
            predicates = [
                _future_predicate(future_row, event) for _, future_row in future.iterrows()
            ]
            # Outcome observability is event-specific.  A missing SKEW value,
            # for example, cannot censor a front-curve outcome whose F1/F2
            # predicate is fully known.  The PIT-selected inputs used to build
            # the predicate already carry their own vintage boundary; the
            # row-wide state/model gate is intentionally not reused here.
            complete = (
                len(future) == horizon
                and all(predicate is not None for predicate in predicates)
                and all(
                    _future_predicate_vintage_eligible(future_row, event)
                    for _, future_row in future.iterrows()
                )
            )
            if not complete:
                records.append(record)
                continue
            if event == "broad_stress_persists_10d":
                observed = sum(bool(value) for value in predicates) >= 5
            else:
                observed = any(bool(value) for value in predicates)
            final_session = pd.Timestamp(future.iloc[-1]["session_date"]).normalize()
            record.update(
                {
                    "label": int(observed),
                    "label_status": "OBSERVED_1" if observed else "OBSERVED_0",
                    "valid_through_session": final_session,
                    "outcome_available_at": pd.Timestamp(decision_as_of(final_session)),
                }
            )
            records.append(record)
    ledger = pd.DataFrame(records)
    return ledger.sort_values(["event_id", "prediction_date"]).reset_index(drop=True)
