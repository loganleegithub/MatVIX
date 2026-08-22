from __future__ import annotations

import numpy as np
import pandas as pd
from conftest import base_state_frame
from scipy.special import expit, logit

from matvix.calendar import decision_as_of, sessions_in_range
from matvix.v3_audit import _fragility_target_ledger, append_calibration_replay


def test_fixed_intercept_replay_has_identity_warmup_and_fixed_slope() -> None:
    dates = sessions_in_range("2024-01-02", "2024-04-30")[:50]
    labels = np.tile([0, 1], 25)
    raw = np.linspace(0.15, 0.65, len(dates))
    frame = pd.DataFrame(
        {
            "event_id": "event",
            "prediction_date": dates,
            "outcome_available_at": [decision_as_of(value) for value in dates],
            "label": labels,
            "label_status": np.where(labels == 1, "OBSERVED_1", "OBSERVED_0"),
            "decision_score": logit(raw),
            "base_probability": raw,
            "base_rate_at_prediction": 0.5,
            "calibrated_probability": np.nan,
            "platt_a": np.nan,
            "platt_b": np.nan,
            "calibration_samples": 0,
            "calibration_converged": False,
        }
    )

    replayed = append_calibration_replay(frame)

    assert replayed.loc[39, "rolling_intercept_method"] == "IDENTITY_WARMUP"
    assert replayed.loc[40, "rolling_intercept_method"] == "ROLLING_INTERCEPT_252"
    row = replayed.loc[40]
    expected = expit(logit(row.base_probability) + row.rolling_intercept_b)
    assert row.rolling_intercept_probability == expected


def test_fragility_label_uses_weather_facts_and_full_five_session_horizon() -> None:
    frame = base_state_frame(7)
    values = {"carry_answer": "SUPPORTIVE", "shock_answer": "CALM", "persistence_answer": "NORMAL", "data_status": "OK", "hard_acute": False, "front_slope30": 0.03, "broad_pressure_day": False, "carry_environment_state": "OPEN", "hard_acute_formal_vintage_eligible": True, "front_curve_formal_vintage_eligible": True, "broad_pressure_day_formal_vintage_eligible": True, "carry_environment_formal_vintage_eligible": True}
    for column, value in values.items():
        frame[column] = value
    frame.loc[3, "front_slope30"] = -0.01

    ledger = _fragility_target_ledger(frame)

    assert ledger.loc[0, "event_status"] == "ELIGIBLE"
    assert ledger.loc[0, "label_status"] == "OBSERVED_1"
    assert ledger.loc[0, "label"] == 1
    assert "FRONT_INVERSION" in ledger.loc[0, "positive_components"]
    assert ledger.loc[2, "label_status"] == "CENSORED"
