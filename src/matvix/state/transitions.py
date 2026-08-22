from __future__ import annotations

import pandas as pd

ACUTE_RELEASE_SHOCK_MAX = 75.0
ACUTE_RELEASE_SESSIONS = 2


def apply_phase_hysteresis(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    published: list[str] = []

    previous_published: str | None = None
    release_streak = 0

    for row in result.itertuples(index=False):
        raw = str(row.raw_phase)
        if raw == "UNKNOWN":
            current = "UNKNOWN"
            release_streak = 0
        elif previous_published == "ACUTE_FRONT_STRESS":
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
            current = raw
            release_streak = 0

        published.append(current)
        previous_published = current

    result["phase"] = published
    return result


def build_state_table(scored_features: pd.DataFrame) -> pd.DataFrame:
    from matvix.state.ontology import add_state_predicates_and_answers
    from matvix.state.scores import add_probability_predictors

    return add_probability_predictors(
        apply_phase_hysteresis(add_state_predicates_and_answers(scored_features))
    )
