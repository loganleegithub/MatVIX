from __future__ import annotations

import copy
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from conftest import base_state_frame, make_observations, make_vx_history

from matvix.acceptance import (
    _audit_carry_duration_facts,
    _audit_oof_training_boundaries,
    _audit_real_observations,
    _audit_real_vx,
    _calibration_integrity_passes,
    _calibration_row_is_arithmetically_valid,
    _completed_published_validation,
    _station_base_rate_reference_assessment,
    _station_curve_formula_valid,
    _station_fragility_boundary_assessment,
    _station_probability_model_assessment,
    _station_tenor_stage_masks,
    build_real_acceptance_report,
)
from matvix.calendar import decision_as_of
from matvix.constants import EVENT_ORDER
from matvix.output import build_daily_output
from matvix.probability.targets import add_carry_duration_facts
from matvix.probability.walk_forward import ProbabilitySpec
from matvix.storage import read_json, write_json


def _event(
    event_status: str = "UNOBSERVABLE",
    model_status: str = "NOT_RUN",
    *,
    probability: float | None = None,
    base_rate: float | None = None,
    uplift: float | None = None,
    probability_kind: str | None = None,
    valid_through_session: str | None = None,
) -> dict[str, object]:
    if model_status == "BASE_RATE_ONLY":
        raw_probability = None
        calibration_method = "NOT_APPLICABLE"
        calibration_samples = calibration_positive = calibration_negative = 0
        intercept_b = None
    elif model_status == "CALIBRATED_MODEL":
        raw_probability = probability
        calibration_method = "ROLLING_INTERCEPT_252"
        calibration_samples = 40
        calibration_positive = calibration_negative = 20
        intercept_b = 0.0
    else:
        raw_probability = None
        calibration_method = None
        calibration_samples = calibration_positive = calibration_negative = None
        intercept_b = None
    return {
        "event_status": event_status,
        "model_status": model_status,
        "probability_kind": probability_kind,
        "raw_probability": raw_probability,
        "probability": probability,
        "base_rate": base_rate,
        "uplift": uplift,
        "calibration_method": calibration_method,
        "calibration_samples": calibration_samples,
        "calibration_positive": calibration_positive,
        "calibration_negative": calibration_negative,
        "intercept_b": intercept_b,
        "valid_through_session": valid_through_session,
        "interpretation": "验收测试",
    }


def _state_and_snapshot() -> tuple[pd.DataFrame, dict[str, object]]:
    row = base_state_frame(40).iloc[-1].copy()
    row["session_date"] = pd.Timestamp("2025-01-02")
    row["feature_methodology_signature"] = "CBOE_V1|CFE_V1"
    row["pit_evidence"] = "ASSUMED"
    row["vx_contract_ids"] = np.asarray([f"VX{i}" for i in range(1, 8)])
    row["vx_settles"] = np.asarray([18.0, 19.0, 20.0, 21.0, 22.0, 23.0, 24.0])
    row["vx_days_to_final"] = np.asarray(
        [10.0, 40.0, 70.0, 100.0, 130.0, 160.0, 190.0]
    )
    events = {event: _event() for event in EVENT_ORDER}
    snapshot = build_daily_output(
        row,
        events,
        manifest_hash="sha256:" + "0" * 64,
    )
    return pd.DataFrame([row]), snapshot


def _empty_targets() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "event_id",
            "prediction_date",
            "event_status",
            "label",
            "label_status",
            "valid_through_session",
            "outcome_available_at",
            "formal_vintage_eligible",
        ]
    )


def _gate(report: dict[str, object], name: str) -> dict[str, object]:
    return next(gate for gate in report["gates"] if gate["name"] == name)  # type: ignore[index]


def test_latest_complete_state_accepts_numpy_curve_arrays() -> None:
    states, snapshot = _state_and_snapshot()
    report = build_real_acceptance_report(
        observations=pd.DataFrame(),
        vx_contracts=pd.DataFrame(),
        states=states,
        targets=_empty_targets(),
        oof=pd.DataFrame(),
        snapshot=snapshot,
    )

    assert _gate(report, "latest_complete_state")["passed"] is True


def test_carry_duration_acceptance_replays_exact_causal_facts() -> None:
    states = base_state_frame(12)
    states["carry_environment_state"] = "CLOSED"
    states["front_pressure"] = True
    states = add_carry_duration_facts(states)

    passed, evidence = _audit_carry_duration_facts(states)
    changed = states.copy()
    changed.loc[5, "carry_spell_age"] = 99.0
    changed_passed, changed_evidence = _audit_carry_duration_facts(changed)
    changed_bounded = states.copy()
    changed_bounded.loc[5, "bounded_log1p_carry_spell_age"] = 99.0
    changed_bounded_passed, changed_bounded_evidence = _audit_carry_duration_facts(
        changed_bounded
    )
    with_legacy = states.copy()
    with_legacy["log1p_carry_spell_age"] = np.log1p(with_legacy["carry_spell_age"])
    legacy_passed, legacy_evidence = _audit_carry_duration_facts(with_legacy)

    assert passed is True
    assert evidence["max_spell_age"] == 12
    assert changed_passed is False
    assert changed_evidence["column_replay"]["carry_spell_age"] is False
    assert changed_bounded_passed is False
    assert (
        changed_bounded_evidence["column_replay"]["bounded_log1p_carry_spell_age"]
        is False
    )
    assert legacy_passed is False
    assert legacy_evidence["legacy_columns"] == ["log1p_carry_spell_age"]


def test_invalid_probability_arithmetic_is_a_failed_acceptance_gate() -> None:
    states, snapshot = _state_and_snapshot()
    broken = copy.deepcopy(snapshot)
    broken["probability_judgment"]["acute_front_stress_5d"] = _event(
        "ELIGIBLE",
        "CALIBRATED_MODEL",
        probability=0.3,
        base_rate=0.2,
        uplift=0.2,
        probability_kind="FEATURE_CONDITIONAL",
        valid_through_session="2025-01-10",
    )

    report = build_real_acceptance_report(
        observations=pd.DataFrame(),
        vx_contracts=pd.DataFrame(),
        states=states,
        targets=_empty_targets(),
        oof=pd.DataFrame(),
        snapshot=broken,
    )

    contract = _gate(report, "snapshot_contract")
    assert contract["passed"] is False
    assert (
        "uplift must equal probability - base_rate" in contract["evidence"]["error"]  # type: ignore[index]
    )


@pytest.fixture(scope="module")
def real_coverage_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp, pd.Series]:
    observations = make_observations("2021-12-01", "2025-01-02")
    sessions = pd.DatetimeIndex(sorted(pd.to_datetime(observations["session_date"]).unique()))
    vx = make_vx_history(sessions)
    snapshot_session = sessions[-1]
    latest_curve = vx.loc[pd.to_datetime(vx["session_date"]).eq(snapshot_session)]
    latest = pd.Series(
        {
            "vx_contract_ids": latest_curve["contract_id"].to_numpy(),
            "vx_settles": latest_curve["settle"].to_numpy(),
        }
    )
    return observations, vx, snapshot_session, latest


@pytest.mark.parametrize(
    ("column", "wrong_value"),
    [
        ("source", "FRED"),
        ("source_symbol", "SP500"),
        ("vintage_kind", "OBSERVED_PIT"),
    ],
)
def test_real_observation_audit_rejects_wrong_source_identity(
    real_coverage_inputs: tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp, pd.Series],
    column: str,
    wrong_value: str,
) -> None:
    observations, _, snapshot_session, _ = real_coverage_inputs
    changed = observations.copy()
    mask = pd.to_datetime(changed["session_date"]).eq(snapshot_session) & changed["series_id"].eq(
        "SPX_CLOSE"
    )
    changed.loc[mask, column] = wrong_value

    baseline_passed, _ = _audit_real_observations(observations, snapshot_session)
    changed_passed, evidence = _audit_real_observations(changed, snapshot_session)

    assert baseline_passed
    assert not changed_passed
    assert evidence["series"]["SPX_CLOSE"]["snapshot_rows_available"] == 0


@pytest.mark.parametrize(
    ("column", "wrong_value"),
    [
        ("source", "CBOE"),
        ("source_symbol", "VX_WEEKLY"),
        ("vintage_kind", "OBSERVED_PIT"),
    ],
)
def test_real_vx_audit_rejects_wrong_source_identity(
    real_coverage_inputs: tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp, pd.Series],
    column: str,
    wrong_value: str,
) -> None:
    _, vx, snapshot_session, latest = real_coverage_inputs
    changed = vx.copy()
    changed.loc[pd.to_datetime(changed["session_date"]).eq(snapshot_session), column] = wrong_value

    baseline_passed, _ = _audit_real_vx(vx, snapshot_session, latest)
    changed_passed, evidence = _audit_real_vx(changed, snapshot_session, latest)

    assert baseline_passed
    assert not changed_passed
    assert evidence["snapshot_contracts_available"] == 0


def test_validation_requires_252_completed_published_oof_but_may_reject_model() -> None:
    dates = pd.bdate_range("2023-01-02", periods=252)
    frame = pd.DataFrame(
        {
            "event_id": "carry_environment_recovers_10d",
            "prediction_date": dates,
            "outcome_available_at": pd.to_datetime(dates, utc=True),
            "label_status": ["OBSERVED_1" if i % 5 == 0 else "OBSERVED_0" for i in range(252)],
            "label": [1 if i % 5 == 0 else 0 for i in range(252)],
            "published_probability": 0.5,
            "base_rate_at_prediction": 0.2,
        }
    )
    snapshot_date = pd.Timestamp("2025-01-02")

    incomplete, incomplete_evidence = _completed_published_validation(
        frame.iloc[:-1], "carry_environment_recovers_10d", snapshot_date
    )
    complete, complete_evidence = _completed_published_validation(
        frame, "carry_environment_recovers_10d", snapshot_date
    )

    assert incomplete is False
    assert incomplete_evidence["samples"] == 251
    assert complete is True
    assert complete_evidence["samples"] == 252
    assert complete_evidence["accepted"] is False


def test_calibration_integrity_does_not_require_model_publication_acceptance() -> None:
    events = {
        event: {
            "raw_oof": 300,
            "published_oof": 100,
            "base_rate_reference_oof": 0,
            "validation_complete": False,
        }
        for event in EVENT_ORDER
    }

    events["broad_stress_persists_10d"].update(
        {"raw_oof": 0, "base_rate_reference_oof": 100}
    )
    assert _calibration_integrity_passes(events, []) is True
    events["broad_stress_persists_10d"]["base_rate_reference_oof"] = 0
    assert _calibration_integrity_passes(events, []) is False


def test_station_curve_formula_replays_f1_f7_facts() -> None:
    settles = [18.0, 19.0, 20.0, 21.0, 22.0, 23.0, 24.0]
    days = [10.0, 40.0, 70.0, 100.0, 130.0, 160.0, 190.0]
    row = pd.Series(
        {
            "vx_contract_ids": [f"VX{i}" for i in range(1, 8)],
            "vx_settles": settles,
            "vx_days_to_final": days,
            "front_curve_level": 18.5,
            "f4_f7_level": 22.5,
            "f4_f7_slope30": np.log(24.0 / 21.0) * 30.0 / 90.0,
            "f4_f7_inversion_share": 0.0,
            "front_to_mid_log_ratio": np.log(22.5 / 18.5),
            "vxcm30": 18.0 / 3.0 + 19.0 * 2.0 / 3.0,
            "vxcm30_source_kind": "DIRECT_BRACKET_INTERPOLATION",
            "vxcm30_methodology": "VXCM30_LINEAR_30D_V2",
        }
    )

    assert _station_curve_formula_valid(row) is True
    row["f4_f7_level"] = 99.0
    assert _station_curve_formula_valid(row) is False


def test_station_probability_model_assessment_preserves_mixed_evidence() -> None:
    events = {
        event: {
            "validation_complete": True,
            "validation": {"accepted": True, "samples": 252},
        }
        for event in EVENT_ORDER
    }
    events["broad_stress_persists_10d"] = {
        "validation_complete": False,
        "validation": {"accepted": False, "samples": 191},
    }
    events["carry_environment_recovers_10d"] = {
        "validation_complete": True,
        "validation": {"accepted": False, "samples": 252},
    }

    status, evidence = _station_probability_model_assessment(events)

    assert status == "FAIL"
    assert evidence["events"]["acute_front_stress_5d"]["status"] == "PASS"
    assert evidence["events"]["broad_stress_persists_10d"]["status"] == (
        "BASE_RATE_ONLY_EXEMPT"
    )
    assert evidence["events"]["carry_environment_recovers_10d"]["status"] == "FAIL"


def test_station_base_rate_reference_is_separate_from_model_pass() -> None:
    calibration = {
        "broad_stress_persists_10d": {
            "publication_policy": "BASE_RATE_ONLY_EXEMPT",
            "validation_complete": True,
            "raw_oof": 0,
            "validation": {"accepted": True, "exempt": True, "samples": 2},
        }
    }
    model_evidence = {
        "events": {"broad_stress_persists_10d": {"status": "BASE_RATE_ONLY_EXEMPT"}},
        "last_eligible_publication": {
            "broad_stress_persists_10d": {
                "model_status": "BASE_RATE_ONLY",
                "matches": True,
            }
        },
    }
    oof = pd.DataFrame(
        {
            "event_id": ["broad_stress_persists_10d"] * 2,
            "raw_probability": [np.nan, np.nan],
            "published_probability": [0.4, 0.5],
            "base_rate_at_prediction": [0.4, 0.5],
            "calibration_method": ["NOT_APPLICABLE", "NOT_APPLICABLE"],
        }
    )

    passed, evidence = _station_base_rate_reference_assessment(
        calibration, model_evidence, oof
    )

    assert passed is True
    assert evidence["model_pass_claimed"] is False
    broken = oof.copy()
    broken.loc[1, "published_probability"] = 0.6
    assert _station_base_rate_reference_assessment(calibration, model_evidence, broken)[0] is False


def test_station_fragility_boundary_requires_absence_and_retained_rejection(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    schema = tmp_path / "schemas" / "daily_output.schema.json"
    schema.parent.mkdir(parents=True)
    shutil.copyfile(project_root / "schemas" / "daily_output.schema.json", schema)
    manifest = read_json(project_root / "MATVIX_V3_RELEASE_MANIFEST.json")
    write_json(manifest, tmp_path / "MATVIX_V3_RELEASE_MANIFEST.json")
    states = pd.DataFrame({"session_date": pd.to_datetime(["2026-08-20"])})
    targets = pd.DataFrame({"event_id": ["acute_front_stress_5d"]})
    oof = pd.DataFrame({"event_id": ["acute_front_stress_5d"]})
    snapshot = {"probability_judgment": {"acute_front_stress_5d": {}}}

    passed, evidence = _station_fragility_boundary_assessment(
        project_dir=tmp_path,
        states=states,
        targets=targets,
        oof=oof,
        latest_snapshot=snapshot,
    )

    assert passed is True
    assert evidence["formal_model_status"] == "NOT_ELIGIBLE"
    contaminated = copy.deepcopy(snapshot)
    contaminated["probability_judgment"]["calm_carry_breaks_5d"] = {}
    assert (
        _station_fragility_boundary_assessment(
            project_dir=tmp_path,
            states=states,
            targets=targets,
            oof=oof,
            latest_snapshot=contaminated,
        )[0]
        is False
    )
    broken_manifest = copy.deepcopy(manifest)
    broken_manifest["scientific_evidence"]["fragility_boundary"][
        "completed_published_oof"
    ] = 115
    write_json(broken_manifest, tmp_path / "MATVIX_V3_RELEASE_MANIFEST.json")
    assert (
        _station_fragility_boundary_assessment(
            project_dir=tmp_path,
            states=states,
            targets=targets,
            oof=oof,
            latest_snapshot=snapshot,
        )[0]
        is False
    )


def test_station_tenor_stage_masks_require_broad_scope_for_diffusing_and_priced() -> None:
    frame = pd.DataFrame(
        {
            "stress_tenor_scope": ["MID", "BROAD", "BROAD", "FRONT"],
            "mid_curve_pressure_state": ["RISING", "RISING", "PRICED", "RECEDING"],
        }
    )

    masks = _station_tenor_stage_masks(frame)

    assert masks["DIFFUSING"].tolist() == [False, True, False, False]
    assert masks["PRICED"].tolist() == [False, False, True, False]
    assert masks["RECEDING"].tolist() == [False, False, False, True]


def test_rolling_intercept_probability_must_match_persisted_intercept() -> None:
    valid = pd.Series(
        {
            "raw_probability": 0.5,
            "intercept_b": 0.0,
            "published_probability": 0.5,
            "calibration_method": "ROLLING_INTERCEPT_252",
        }
    )
    invalid = valid.copy()
    invalid["published_probability"] = 0.6

    assert _calibration_row_is_arithmetically_valid(valid)
    assert not _calibration_row_is_arithmetically_valid(invalid)


def test_oof_gate_recomputes_and_rejects_false_training_boundary() -> None:
    states = base_state_frame(320)
    dates = pd.to_datetime(states["session_date"]).dt.normalize()
    labels = np.arange(len(states)) % 2
    targets = pd.DataFrame(
        {
            "event_id": "acute_front_stress_5d",
            "prediction_date": dates,
            "event_status": "ELIGIBLE",
            "label": labels,
            "label_status": np.where(labels == 1, "OBSERVED_1", "OBSERVED_0"),
            "outcome_available_at": [decision_as_of(date) for date in dates],
        }
    )
    prediction_index = 300
    training_end = prediction_index - 20
    training_count = training_end + 1
    training_positive = int(labels[:training_count].sum())
    base_count = prediction_index
    base_positive = int(labels[:base_count].sum())
    prediction_date = dates.iloc[prediction_index]
    oof = pd.DataFrame(
        [
            {
                "event_id": "acute_front_stress_5d",
                "prediction_date": prediction_date,
                "outcome_available_at": decision_as_of(prediction_date),
                "label": int(labels[prediction_index]),
                "label_status": ("OBSERVED_1" if labels[prediction_index] else "OBSERVED_0"),
                "raw_probability": 0.5,
                "published_probability": 0.5,
                "base_rate_at_prediction": (base_positive + 1) / (base_count + 2),
                "base_rate_samples": base_count,
                "base_rate_positive": base_positive,
                "base_rate_negative": base_count - base_positive,
                "training_samples": training_count,
                "training_positive": training_positive,
                "training_negative": training_count - training_positive,
                # Deliberately claims the current prediction was in its own training set.
                "training_latest_prediction_date": prediction_date,
                "training_latest_outcome_available_at": decision_as_of(dates.iloc[training_end]),
                "converged": True,
                "calibration_method": "IDENTITY_WARMUP",
                "calibration_samples": 0,
                "calibration_positive": 0,
                "calibration_negative": 0,
                "intercept_b": np.nan,
            }
        ]
    )

    passed, evidence, _ = _audit_oof_training_boundaries(states, targets, oof, ProbabilitySpec())

    assert passed is False
    assert any(
        "persisted training boundary mismatch" in violation
        for violation in evidence["first_violations"]
    )
