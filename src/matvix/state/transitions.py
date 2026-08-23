from __future__ import annotations

import pandas as pd

from matvix.calendar import next_session

ACUTE_RELEASE_SHOCK_MAX = 75.0
ACUTE_RELEASE_SESSIONS = 2
RISK_ON_CONFIRMATION_SESSIONS = 3
RISK_ON_CONFIRMATION_TRANSITIONS = frozenset(
    {
        ("MIXED_TRANSITION", "TAIL_RICH_QUIET_CURVE"),
        ("MIXED_TRANSITION", "CARRY_SUPPORTIVE_LOW_STRESS"),
        ("TAIL_RICH_QUIET_CURVE", "CARRY_SUPPORTIVE_LOW_STRESS"),
    }
)


def _formal_session_gap(previous: object, current: object) -> bool:
    if previous is None or current is None or pd.isna(previous) or pd.isna(current):
        return previous is not None
    return bool(
        pd.Timestamp(current).normalize() != next_session(pd.Timestamp(previous)).normalize()
    )


def apply_phase_hysteresis(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    published: list[str] = []

    previous_published: str | None = None
    release_streak = 0
    pending_risk_on: str | None = None
    pending_risk_on_streak = 0
    previous_session: object = None

    for row in result.itertuples(index=False):
        raw = str(row.raw_phase)
        current_session = getattr(row, "session_date", None)
        if hasattr(row, "session_date") and _formal_session_gap(
            previous_session, current_session
        ):
            pending_risk_on = None
            pending_risk_on_streak = 0

        row_ok = str(getattr(row, "data_status", "OK")) == "OK"
        if raw == "UNKNOWN" or not row_ok:
            current = raw
            release_streak = 0
            pending_risk_on = None
            pending_risk_on_streak = 0
        elif previous_published == "ACUTE_FRONT_STRESS":
            pending_risk_on = None
            pending_risk_on_streak = 0
            if raw == "ACUTE_FRONT_STRESS":
                current = previous_published
                release_streak = 0
            elif (
                pd.notna(row.hard_acute)
                and not bool(row.hard_acute)
                and float(row.shock_score) < ACUTE_RELEASE_SHOCK_MAX
            ):
                release_streak += 1
                if release_streak >= ACUTE_RELEASE_SESSIONS:
                    current = raw
                    release_streak = 0
                else:
                    current = previous_published
            else:
                current = previous_published
                release_streak = 0
        else:
            release_streak = 0
            transition = (previous_published, raw)
            if transition in RISK_ON_CONFIRMATION_TRANSITIONS:
                if pending_risk_on == raw:
                    pending_risk_on_streak += 1
                else:
                    pending_risk_on = raw
                    pending_risk_on_streak = 1
                if pending_risk_on_streak >= RISK_ON_CONFIRMATION_SESSIONS:
                    current = raw
                    pending_risk_on = None
                    pending_risk_on_streak = 0
                else:
                    current = str(previous_published)
            else:
                current = raw
                pending_risk_on = None
                pending_risk_on_streak = 0

        published.append(current)
        previous_published = current
        previous_session = current_session

    result["phase"] = published
    return result


def build_state_table(scored_features: pd.DataFrame) -> pd.DataFrame:
    from matvix.state.ontology import add_state_predicates_and_answers
    from matvix.state.scores import add_probability_predictors

    return add_probability_predictors(
        apply_phase_hysteresis(add_state_predicates_and_answers(scored_features))
    )
