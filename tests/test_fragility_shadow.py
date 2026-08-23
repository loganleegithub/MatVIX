from __future__ import annotations

import pandas as pd
from conftest import base_state_frame

from matvix.constants import EVENT_ORDER, LOGISTIC_FEATURES
from matvix.fragility_shadow import (
    EVENT_ID,
    PREDICTORS,
    SPEC_SHA256,
    adapter_spec_sha256,
    build_shadow_target_ledger,
    build_v3_adapter,
)


def test_shadow_spec_is_frozen_outside_formal_probability_surface() -> None:
    assert adapter_spec_sha256() == SPEC_SHA256
    assert EVENT_ID not in EVENT_ORDER
    assert EVENT_ID not in LOGISTIC_FEATURES


def test_shadow_target_requires_complete_fifth_session() -> None:
    states = base_state_frame(7)
    states["carry_answer"] = "SUPPORTIVE"
    for predictor in PREDICTORS:
        states[predictor] = 0.5
    for flag in ("hard_acute_formal_vintage_eligible", "front_curve_formal_vintage_eligible",
                 "broad_pressure_day_formal_vintage_eligible", "carry_environment_formal_vintage_eligible"):
        states[flag] = True
    states.loc[1, "broad_pressure_day"] = True
    ledger = build_shadow_target_ledger(states)
    assert ledger.loc[0, "label_status"] == "OBSERVED_1"
    assert ledger.loc[0, "valid_through_session"] == states.loc[5, "session_date"]
    states.loc[4, "carry_environment_formal_vintage_eligible"] = False
    assert build_shadow_target_ledger(states).loc[0, "label_status"] == "CENSORED"


def test_v3_shadow_can_only_remove_base_short_exposure() -> None:
    states = base_state_frame(4)
    states["carry_answer"] = "SUPPORTIVE"
    states.loc[3, "persistence_answer"] = "DIFFUSING"
    scores = pd.DataFrame({"prediction_date": states.loc[:2, "session_date"],
                           "published_probability": [0.6, 0.4, 0.5],
                           "base_rate_at_prediction": [0.5, 0.5, 0.5],
                           "calibration_method": ["IDENTITY_WARMUP"] * 3})
    adapter = build_v3_adapter(states, scores)
    assert adapter["base_short_allowed"].tolist() == [True, True, True, False]
    assert adapter["unqualified_fragility_veto_shadow"].tolist() == [True, False, False, False]
    assert adapter["short_allowed_v3"].tolist() == [False, True, True, False]
    assert adapter.loc[3, "persistence"] == "DIFFUSING"
    assert not bool(adapter.loc[3, "shadow_score_available"])
