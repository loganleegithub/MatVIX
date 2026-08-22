from __future__ import annotations

import pytest
from conftest import base_state_frame

from matvix.constants import EVENT_ORDER
from matvix.output import build_daily_output, validate_daily_output


def unobservable_events():
    return {
        event: {
            "event_status": "UNOBSERVABLE",
            "model_status": "NOT_RUN",
            "probability_kind": None,
            "raw_probability": None,
            "probability": None,
            "base_rate": None,
            "uplift": None,
            "calibration_method": None,
            "calibration_samples": None,
            "calibration_positive": None,
            "calibration_negative": None,
            "intercept_b": None,
            "valid_through_session": None,
            "interpretation": "当前输入不足，无法观察该问题",
        }
        for event in EVENT_ORDER
    }


def test_partial_output_nulls_baseline_and_unknown_story() -> None:
    row = base_state_frame(1).iloc[0].copy()
    row["data_status"] = "PARTIAL"
    row["phase"] = "UNKNOWN"
    row["pressure_level"] = "UNKNOWN"
    row["direction"] = "UNKNOWN"
    row["carry_answer"] = "UNKNOWN"
    row["shock_answer"] = "UNKNOWN"
    row["tail_answer"] = "UNKNOWN"
    row["persistence_answer"] = "UNKNOWN"
    row["repair_answer"] = "UNKNOWN"
    row["session_date"] = "2025-01-02"
    payload = build_daily_output(row, unobservable_events(), manifest_hash="sha256:" + "0" * 64)
    validate_daily_output(payload)
    assert payload["market_story"]["baseline_score"] is None
    assert payload["market_story"]["phase"] == "UNKNOWN"


def test_schema_rejects_extra_event_field() -> None:
    row = base_state_frame(1).iloc[0].copy()
    row["session_date"] = "2025-01-02"
    payload = build_daily_output(row, unobservable_events(), manifest_hash="sha256:" + "0" * 64)
    payload["probability_judgment"]["acute_front_stress_5d"]["eligible"] = False
    with pytest.raises(ValueError):
        validate_daily_output(payload)


def test_schema_rejects_not_applicable_zero_probability() -> None:
    row = base_state_frame(1).iloc[0].copy()
    row["session_date"] = "2025-01-02"
    events = unobservable_events()
    events["acute_front_stress_5d"] = {
        "event_status": "NOT_APPLICABLE",
        "model_status": "NOT_RUN",
        "probability_kind": None,
        "raw_probability": None,
        "probability": 0.0,
        "base_rate": None,
        "uplift": None,
        "calibration_method": None,
        "calibration_samples": None,
        "calibration_positive": None,
        "calibration_negative": None,
        "intercept_b": None,
        "valid_through_session": None,
        "interpretation": "当前状态已存在或该转移问题不适用",
    }
    payload = build_daily_output(row, events, manifest_hash="sha256:" + "0" * 64)
    with pytest.raises(ValueError):
        validate_daily_output(payload)
