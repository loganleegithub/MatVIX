from __future__ import annotations

import pandas as pd

IMMEDIATE_PHASES = {
    "ACUTE_FRONT_STRESS",
    "REPAIR_IN_PROGRESS",
    "BROAD_PERSISTENT_STRESS",
}


def apply_phase_hysteresis(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    published: list[str] = []
    candidates: list[str | None] = []
    streaks: list[int] = []

    previous_published: str | None = None
    previous_candidate: str | None = None
    previous_streak = 0

    for row in result.itertuples(index=False):
        raw = str(row.raw_phase)
        if raw == "UNKNOWN":
            current = "UNKNOWN"
            candidate = None
            streak = 0
        elif previous_published is None or previous_published == "UNKNOWN":
            current = raw
            candidate = None
            streak = 0
        elif previous_published == "ACUTE_FRONT_STRESS":
            if raw == "ACUTE_FRONT_STRESS":
                current = previous_published
                candidate = None
                streak = 0
            elif (
                pd.notna(row.hard_acute)
                and not bool(row.hard_acute)
                and float(row.shock_score) < 75
            ):
                candidate = raw
                # Acute exit confirms the release condition, not one particular
                # successor phase.  The raw phase may legitimately evolve across
                # the two release sessions while hard acute remains released.
                streak = previous_streak + 1
                if streak >= 2:
                    current = raw
                    candidate = None
                    streak = 0
                else:
                    current = previous_published
            else:
                current = previous_published
                candidate = None
                streak = 0
        elif raw in IMMEDIATE_PHASES:
            current = raw
            candidate = None
            streak = 0
        else:
            candidate = raw
            streak = previous_streak + 1 if previous_candidate == raw else 1
            if streak >= 2:
                current = raw
                candidate = None
                streak = 0
            else:
                current = previous_published

        published.append(current)
        candidates.append(candidate)
        streaks.append(streak)
        previous_published = current
        previous_candidate = candidate
        previous_streak = streak

    result["phase"] = published
    result["candidate_phase"] = candidates
    result["candidate_streak"] = streaks
    return result


def build_state_table(scored_features: pd.DataFrame) -> pd.DataFrame:
    from matvix.state.ontology import add_state_predicates_and_answers
    from matvix.state.scores import add_probability_predictors

    return add_probability_predictors(
        apply_phase_hysteresis(add_state_predicates_and_answers(scored_features))
    )
