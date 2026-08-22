from __future__ import annotations

import copy

import jsonschema
import numpy as np
import pandas as pd
import pytest
from conftest import base_state_frame
from sklearn.linear_model import LogisticRegression

from matvix.calendar import add_sessions, decision_as_of, sessions_in_range
from matvix.constants import EVENT_ORDER, FEATURE_CONDITIONAL_EVENTS, LOGISTIC_FEATURES
from matvix.output import build_daily_output, load_schema, validate_daily_output
from matvix.probability import engine as probability_engine
from matvix.probability.baseline import beta_smoothed_base_rate
from matvix.probability.calibration import (
    acceptance_metrics,
    apply_intercept,
    exact_ece_252,
    fit_intercept,
)
from matvix.probability.engine import (
    ProbabilityArtifactContractError,
    build_probability_artifact_contract,
    outlook_answer,
    resolve_probability_artifacts,
    run_probability_job,
    validate_probability_artifact_contract,
)
from matvix.probability.targets import (
    add_carry_duration_facts,
    build_target_ledger,
    event_status,
)
from matvix.probability.walk_forward import (
    ProbabilitySpec,
    _fit_model,
    build_oof_ledger,
    make_logistic,
)


def test_observable_then_onset_priority() -> None:
    row = base_state_frame(1).iloc[0].copy()
    row["formal_vintage_eligible"] = False
    row["hard_acute"] = True
    assert event_status(row, "acute_front_stress_5d") == "UNOBSERVABLE"
    row["formal_vintage_eligible"] = True
    assert event_status(row, "acute_front_stress_5d") == "NOT_APPLICABLE"
    row["hard_acute"] = False
    assert event_status(row, "acute_front_stress_5d") == "ELIGIBLE"


def test_event_onsets_for_all_five_targets() -> None:
    frame = base_state_frame(1)
    row = frame.iloc[0].copy()
    assert event_status(row, "acute_front_stress_5d") == "ELIGIBLE"
    assert event_status(row, "front_inversion_5d") == "ELIGIBLE"
    assert event_status(row, "mid_curve_pressure_accelerates_5d") == "ELIGIBLE"
    assert event_status(row, "broad_stress_persists_10d") == "NOT_APPLICABLE"
    assert event_status(row, "carry_environment_recovers_10d") == "NOT_APPLICABLE"

    row["broad_pressure_day"] = True
    assert event_status(row, "broad_stress_persists_10d") == "ELIGIBLE"

    row["front_pressure"] = True
    assert event_status(row, "carry_environment_recovers_10d") == "ELIGIBLE"


def test_acute_label_boundary_and_full_horizon() -> None:
    frame = base_state_frame(7)
    frame.loc[3, "hard_acute"] = True
    ledger = build_target_ledger(frame)
    row = ledger[
        (ledger.event_id == "acute_front_stress_5d")
        & (ledger.prediction_date == frame.loc[0, "session_date"])
    ].iloc[0]
    assert row.label_status == "OBSERVED_1" and row.label == 1
    tail = ledger[
        (ledger.event_id == "acute_front_stress_5d")
        & (ledger.prediction_date == frame.loc[3, "session_date"])
    ].iloc[0]
    assert tail.label_status == "NOT_APPLICABLE"


def test_front_inversion_label_and_current_inversion_not_applicable() -> None:
    frame = base_state_frame(7)
    frame.loc[2, "front_slope30"] = -0.001
    ledger = build_target_ledger(frame)
    first = ledger[
        (ledger.event_id == "front_inversion_5d")
        & (ledger.prediction_date == frame.loc[0, "session_date"])
    ].iloc[0]
    inverted = ledger[
        (ledger.event_id == "front_inversion_5d")
        & (ledger.prediction_date == frame.loc[2, "session_date"])
    ].iloc[0]
    assert first.label == 1
    assert inverted.label_status == "NOT_APPLICABLE"


def test_mid_curve_acceleration_uses_future_rising_state() -> None:
    frame = base_state_frame(7)
    frame.loc[3, "mid_curve_pressure_state"] = "RISING"
    ledger = build_target_ledger(frame)
    row = ledger[
        (ledger.event_id == "mid_curve_pressure_accelerates_5d")
        & (ledger.prediction_date == frame.loc[0, "session_date"])
    ].iloc[0]
    assert row.label == 1


def test_broad_persistence_requires_five_of_next_ten_sessions() -> None:
    frame = base_state_frame(12)
    frame.loc[0, "broad_pressure_day"] = True
    frame.loc[[1, 3, 5, 7], "broad_pressure_day"] = True
    ledger = build_target_ledger(frame)
    row = ledger[
        (ledger.event_id == "broad_stress_persists_10d")
        & (ledger.prediction_date == frame.loc[0, "session_date"])
    ].iloc[0]
    assert row.label == 0

    frame.loc[9, "broad_pressure_day"] = True
    ledger = build_target_ledger(frame)
    row = ledger[
        (ledger.event_id == "broad_stress_persists_10d")
        & (ledger.prediction_date == frame.loc[0, "session_date"])
    ].iloc[0]
    assert row.label == 1


def test_carry_recovery_uses_future_open_state() -> None:
    frame = base_state_frame(12)
    frame.loc[0, "front_pressure"] = True
    frame.loc[6, "carry_environment_state"] = "OPEN"
    ledger = build_target_ledger(frame)
    row = ledger[
        (ledger.event_id == "carry_environment_recovers_10d")
        & (ledger.prediction_date == frame.loc[0, "session_date"])
    ].iloc[0]
    assert row.label == 1


def test_carry_duration_facts_reset_on_unknown_not_applicable_and_gap() -> None:
    frame = base_state_frame(8)
    frame["carry_environment_state"] = "CLOSED"
    frame["front_pressure"] = True
    frame.loc[2, "data_status"] = "PARTIAL"
    frame.loc[[3, 4], "carry_environment_state"] = "RECOVERING"
    frame.loc[5, "carry_environment_state"] = "OPEN"

    facts = add_carry_duration_facts(frame)

    np.testing.assert_allclose(
        facts["carry_spell_age"].to_numpy()[:6],
        [1.0, 2.0, np.nan, 1.0, 2.0, np.nan],
        equal_nan=True,
    )
    assert facts.loc[
        [0, 1, 3, 4, 6, 7], "bounded_log1p_carry_spell_age"
    ].to_numpy() == pytest.approx(np.log1p([1, 2, 1, 2, 1, 2]))
    assert facts.loc[[0, 1, 3, 4, 6, 7], "carry_recovering_flag"].tolist() == [
        0.0,
        0.0,
        1.0,
        1.0,
        0.0,
        0.0,
    ]

    with_gap = base_state_frame(4)
    with_gap["carry_environment_state"] = "CLOSED"
    with_gap["front_pressure"] = True
    with_gap = with_gap.drop(index=2).reset_index(drop=True)
    gap_facts = add_carry_duration_facts(with_gap)
    assert gap_facts.iloc[-1]["carry_spell_age"] == 1.0


def test_carry_duration_transform_caps_at_twenty_and_removes_unbounded_fact() -> None:
    frame = base_state_frame(25)
    frame["carry_environment_state"] = "CLOSED"
    frame["front_pressure"] = True
    frame["log1p_carry_spell_age"] = 999.0

    facts = add_carry_duration_facts(frame)

    assert "log1p_carry_spell_age" not in facts
    assert facts.loc[19, "bounded_log1p_carry_spell_age"] == pytest.approx(np.log1p(20))
    assert facts.loc[24, "carry_spell_age"] == 25.0
    assert facts.loc[24, "bounded_log1p_carry_spell_age"] == pytest.approx(np.log1p(20))


def test_carry_predictor_order_is_duration_conditioned_fixed_10d() -> None:
    assert LOGISTIC_FEATURES["carry_environment_recovers_10d"] == [
        "repair_scaled",
        "p_d5_front_slope30",
        "p_neg_d5_near_stress",
        "p_d5_f4_f7_slope30",
        "p_neg_d5_log_f4_f7_level",
        "shock_scaled",
        "bounded_log1p_carry_spell_age",
        "carry_recovering_flag",
    ]


def test_missing_future_field_censors_not_zero() -> None:
    frame = base_state_frame(7)
    frame["hard_acute"] = frame["hard_acute"].astype("boolean")
    frame.loc[3, "hard_acute"] = pd.NA
    ledger = build_target_ledger(frame)
    row = ledger[
        (ledger.event_id == "acute_front_stress_5d")
        & (ledger.prediction_date == frame.loc[0, "session_date"])
    ].iloc[0]
    assert row.label_status == "CENSORED" and pd.isna(row.label)


def test_backtested_future_vintage_censors() -> None:
    frame = base_state_frame(7)
    frame.loc[2, "formal_vintage_eligible"] = False
    ledger = build_target_ledger(frame)
    row = ledger[
        (ledger.event_id == "front_inversion_5d")
        & (ledger.prediction_date == frame.loc[0, "session_date"])
    ].iloc[0]
    assert row.label_status == "CENSORED"


def test_unrelated_future_partial_status_does_not_censor_event_predicate() -> None:
    frame = base_state_frame(7)
    frame.loc[3, "data_status"] = "PARTIAL"
    frame.loc[3, "formal_vintage_eligible"] = False
    frame["front_curve_formal_vintage_eligible"] = True
    frame["front_slope30"] = 0.03

    ledger = build_target_ledger(frame)
    row = ledger[
        (ledger.event_id == "front_inversion_5d")
        & (ledger.prediction_date == frame.loc[0, "session_date"])
    ].iloc[0]

    assert row.label_status == "OBSERVED_0"
    assert row.label == 0


@pytest.mark.parametrize(
    ("event", "predicate_flag"),
    [
        ("acute_front_stress_5d", "hard_acute_formal_vintage_eligible"),
        ("mid_curve_pressure_accelerates_5d", "mid_curve_formal_vintage_eligible"),
        ("broad_stress_persists_10d", "broad_pressure_day_formal_vintage_eligible"),
        ("carry_environment_recovers_10d", "carry_environment_formal_vintage_eligible"),
    ],
)
def test_unrelated_future_gap_does_not_censor_other_event_predicates(
    event: str, predicate_flag: str
) -> None:
    frame = base_state_frame(25)
    frame.loc[0, "broad_pressure_day"] = True
    frame.loc[0, "front_pressure"] = True
    frame.loc[3, "data_status"] = "PARTIAL"
    frame.loc[3, "formal_vintage_eligible"] = False
    frame[predicate_flag] = True

    ledger = build_target_ledger(frame)
    row = ledger.loc[
        ledger["event_id"].eq(event) & ledger["prediction_date"].eq(frame.loc[0, "session_date"])
    ].iloc[0]

    assert row["label_status"] == "OBSERVED_0"


def test_positive_outcome_available_only_after_full_horizon() -> None:
    frame = base_state_frame(7)
    frame.loc[1, "hard_acute"] = True
    ledger = build_target_ledger(frame)
    row = ledger[
        (ledger.event_id == "acute_front_stress_5d")
        & (ledger.prediction_date == frame.loc[0, "session_date"])
    ].iloc[0]
    assert row.valid_through_session == frame.loc[5, "session_date"]


def test_beta_base_rate_smoothing_and_minimum() -> None:
    assert beta_smoothed_base_rate([1] * 251)[0] is None
    rate, n, positive, negative = beta_smoothed_base_rate([1, 0] * 126)
    assert (n, positive, negative) == (252, 126, 126)
    assert rate == pytest.approx(127 / 254)


def test_fixed_logistic_parameters() -> None:
    model = make_logistic()
    params = model.get_params()
    expected = {
        "penalty": "l2",
        "C": 1.0,
        "solver": "lbfgs",
        "fit_intercept": True,
        "dual": False,
        "class_weight": None,
        "warm_start": False,
        "tol": 1e-8,
        "max_iter": 1500,
        "random_state": 0,
    }
    for key, value in expected.items():
        assert params[key] == value


def test_logistic_golden_probability() -> None:
    x = np.array([[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [1.0, 1.0], [0.2, 0.8], [0.8, 0.2]])
    y = np.array([0, 0, 1, 1, 0, 1])
    model = LogisticRegression(
        penalty="l2",
        C=1.0,
        solver="lbfgs",
        fit_intercept=True,
        dual=False,
        class_weight=None,
        warm_start=False,
        tol=1e-8,
        max_iter=1500,
        random_state=0,
    ).fit(x, y)
    probability = model.predict_proba(np.array([[0.7, 0.3]]))[0, 1]
    # Frozen against scikit-learn 1.7.2; 1.8.0 produces the same lbfgs result here.
    assert probability == pytest.approx(0.5597825227001174, abs=1e-8)


def test_fit_model_enforces_minimums_and_recent_1500() -> None:
    event = "front_inversion_5d"
    features = LOGISTIC_FEATURES[event]
    n = 1700
    frame = pd.DataFrame({feature: np.linspace(0, 1, n) for feature in features})
    frame["label"] = np.tile([0, 1], n // 2)
    model, meta = _fit_model(
        frame,
        event,
        ProbabilitySpec(training_min=100, training_min_positive=20, training_min_negative=20),
    )
    assert model is not None and meta["training_samples"] == 1500


def _oof_fixture() -> tuple[pd.DataFrame, pd.DataFrame, ProbabilitySpec]:
    event = "front_inversion_5d"
    dates = sessions_in_range("2024-01-02", "2024-07-31")[:100]
    features = LOGISTIC_FEATURES[event]
    state = pd.DataFrame({"session_date": dates})
    for offset, feature in enumerate(features):
        state[feature] = (np.arange(len(dates)) % (7 + offset)) / float(7 + offset)
    labels = (np.arange(len(dates)) % 4 == 0).astype(int)
    targets = pd.DataFrame(
        {
            "event_id": event,
            "prediction_date": dates,
            "event_status": "ELIGIBLE",
            "label": labels,
            "label_status": np.where(labels == 1, "OBSERVED_1", "OBSERVED_0"),
            "horizon_sessions": 5,
            "valid_through_session": [add_sessions(day, 5) for day in dates],
            "outcome_available_at": [decision_as_of(add_sessions(day, 5)) for day in dates],
            "formal_vintage_eligible": True,
        }
    )
    spec = ProbabilitySpec(
        base_rate_min=10,
        training_min=20,
        training_min_positive=4,
        training_min_negative=4,
        purge_sessions=5,
        calibration_max=30,
        calibration_min_positive=2,
        calibration_min_negative=2,
    )
    return state, targets, spec


def test_oof_training_respects_purge_and_completed_outcomes() -> None:
    state, targets, spec = _oof_fixture()
    oof = build_oof_ledger(state, targets, "front_inversion_5d", spec=spec)

    assert not oof.empty
    for row in oof.itertuples(index=False):
        assert pd.Timestamp(row.training_latest_prediction_date) <= add_sessions(
            row.prediction_date, -spec.purge_sessions
        )
        assert pd.Timestamp(row.training_latest_outcome_available_at).tz_convert(
            "UTC"
        ) <= pd.Timestamp(decision_as_of(row.prediction_date)).tz_convert("UTC")


def test_future_label_change_cannot_change_prior_oof_predictions() -> None:
    state, targets, spec = _oof_fixture()
    original = build_oof_ledger(state, targets, "front_inversion_5d", spec=spec)
    cutoff = pd.Timestamp(state.iloc[70]["session_date"])

    changed = targets.copy()
    future = pd.to_datetime(changed["prediction_date"]) > cutoff
    changed.loc[future, "label"] = 1 - changed.loc[future, "label"].astype(int)
    changed.loc[future, "label_status"] = np.where(
        changed.loc[future, "label"].eq(1), "OBSERVED_1", "OBSERVED_0"
    )
    rerun = build_oof_ledger(state, changed, "front_inversion_5d", spec=spec)

    left = original.loc[pd.to_datetime(original["prediction_date"]) <= cutoff].reset_index(
        drop=True
    )
    right = rerun.loc[pd.to_datetime(rerun["prediction_date"]) <= cutoff].reset_index(drop=True)
    pd.testing.assert_frame_equal(left, right)


def test_censored_outcome_does_not_erase_the_real_oof_prediction() -> None:
    state, targets, spec = _oof_fixture()
    prediction_date = pd.Timestamp(state.iloc[70]["session_date"])
    original = build_oof_ledger(state, targets, "front_inversion_5d", spec=spec)

    censored_targets = targets.copy()
    selected = pd.to_datetime(censored_targets["prediction_date"]).eq(prediction_date)
    censored_targets.loc[selected, "label"] = np.nan
    censored_targets.loc[selected, "label_status"] = "CENSORED"
    censored_targets.loc[selected, "outcome_available_at"] = pd.NaT
    rerun = build_oof_ledger(state, censored_targets, "front_inversion_5d", spec=spec)

    before = original.loc[pd.to_datetime(original["prediction_date"]).eq(prediction_date)].iloc[0]
    after = rerun.loc[pd.to_datetime(rerun["prediction_date"]).eq(prediction_date)].iloc[0]
    assert after["label_status"] == "CENSORED"
    assert pd.isna(after["label"])
    assert after["raw_probability"] == pytest.approx(before["raw_probability"], abs=1e-12)
    assert after["published_probability"] == pytest.approx(
        before["published_probability"], abs=1e-12
    )


def test_probability_job_reuses_supplied_history_artifacts(monkeypatch) -> None:
    frame = base_state_frame(30)
    targets = build_target_ledger(frame)

    def unexpected_rebuild(*args, **kwargs):
        raise AssertionError("probability history artifacts were rebuilt")

    monkeypatch.setattr(probability_engine, "prepare_probability_artifacts", unexpected_rebuild)
    _, _, returned_targets, returned_oof = run_probability_job(
        frame,
        prediction_date=frame.iloc[-1]["session_date"],
        formal_runtime_required=False,
        target_ledger=targets,
        oof_ledger=pd.DataFrame(),
    )
    assert returned_targets is targets
    assert returned_oof.empty


def _artifact_state(n: int) -> pd.DataFrame:
    frame = base_state_frame(n)
    index = np.arange(n)
    frame["hard_acute"] = index % 13 == 0
    frame["front_slope30"] = np.where(index % 11 == 0, -0.01, 0.03)
    frame["mid_curve_pressure_state"] = np.where(index % 9 == 0, "RISING", "QUIET")
    frame["broad_pressure_day"] = index % 10 <= 2
    frame["front_pressure"] = index % 8 == 0
    frame["carry_environment_state"] = np.where(index % 9 == 0, "OPEN", "CLOSED")
    for offset, feature in enumerate(
        dict.fromkeys(value for features in LOGISTIC_FEATURES.values() for value in features)
    ):
        frame[feature] = ((index * (offset + 3) + offset) % 19) / 18.0
    return frame


def _artifact_spec() -> ProbabilitySpec:
    return ProbabilitySpec(
        base_rate_min=5,
        training_min=12,
        training_min_positive=1,
        training_min_negative=1,
        purge_sessions=5,
        calibration_max=30,
        calibration_min_positive=1,
        calibration_min_negative=1,
    )


def test_probability_artifact_exact_digest_reuses_without_rebuild(monkeypatch) -> None:
    state = _artifact_state(80)
    spec = _artifact_spec()
    targets, oof = probability_engine.prepare_probability_artifacts(
        state, spec=spec, formal_runtime_required=False
    )
    contract = build_probability_artifact_contract(
        state,
        targets,
        oof,
        spec=spec,
        formal_runtime_required=False,
    )

    def unexpected_rebuild(*args, **kwargs):
        raise AssertionError("exact probability cache was rebuilt")

    monkeypatch.setattr(probability_engine, "prepare_probability_artifacts", unexpected_rebuild)
    reused_targets, reused_oof, reused_contract, action = resolve_probability_artifacts(
        state,
        cached_targets=targets,
        cached_oof=oof,
        cached_contract=contract,
        spec=spec,
        formal_runtime_required=False,
    )
    assert action == "EXACT_CACHE_HIT"
    assert reused_targets is targets
    assert reused_oof is oof
    assert reused_contract is contract


def test_probability_artifact_append_fits_only_new_date_and_preserves_predictions(
    monkeypatch,
) -> None:
    initial = _artifact_state(80)
    appended = _artifact_state(81)
    spec = _artifact_spec()
    targets, oof = probability_engine.prepare_probability_artifacts(
        initial, spec=spec, formal_runtime_required=False
    )
    contract = build_probability_artifact_contract(
        initial,
        targets,
        oof,
        spec=spec,
        formal_runtime_required=False,
    )
    original_fit = probability_engine.extend_oof_ledger.__globals__["_fit_model"]
    fit_events: list[str] = []

    def recording_fit(training, event, fit_spec):
        fit_events.append(event)
        return original_fit(training, event, fit_spec)

    monkeypatch.setitem(
        probability_engine.extend_oof_ledger.__globals__, "_fit_model", recording_fit
    )
    _, updated_oof, updated_contract, action = resolve_probability_artifacts(
        appended,
        cached_targets=targets,
        cached_oof=oof,
        cached_contract=contract,
        spec=spec,
        formal_runtime_required=False,
    )

    assert action == "INCREMENTAL_APPEND"
    assert updated_contract["previous_state_rows"] == len(initial)
    assert fit_events == list(FEATURE_CONDITIONAL_EVENTS)
    immutable_prediction_columns = [
        "event_id",
        "prediction_date",
        "raw_probability",
        "base_rate_at_prediction",
        "training_latest_prediction_date",
        "training_latest_outcome_available_at",
        "published_probability",
        "calibration_method",
        "calibration_samples",
        "calibration_positive",
        "calibration_negative",
        "intercept_b",
    ]
    old_keys = oof[["event_id", "prediction_date"]]
    preserved = updated_oof.merge(old_keys, on=["event_id", "prediction_date"], how="inner")
    expected = oof.sort_values(["event_id", "prediction_date"])[
        immutable_prediction_columns
    ].reset_index(drop=True)
    actual = preserved.sort_values(["event_id", "prediction_date"])[
        immutable_prediction_columns
    ].reset_index(drop=True)
    pd.testing.assert_frame_equal(actual, expected, check_dtype=False)
    for column in (
        "raw_probability",
        "base_rate_at_prediction",
        "published_probability",
        "intercept_b",
    ):
        assert (
            actual[column].to_numpy(dtype=np.float64).tobytes()
            == expected[column].to_numpy(dtype=np.float64).tobytes()
        )


def test_probability_artifact_historical_revision_forces_full_rebuild(monkeypatch) -> None:
    state = _artifact_state(80)
    spec = _artifact_spec()
    targets, oof = probability_engine.prepare_probability_artifacts(
        state, spec=spec, formal_runtime_required=False
    )
    contract = build_probability_artifact_contract(
        state,
        targets,
        oof,
        spec=spec,
        formal_runtime_required=False,
    )
    revised = state.copy()
    revised.loc[20, "shock_scaled"] = float(revised.loc[20, "shock_scaled"]) + 0.01
    original_prepare = probability_engine.prepare_probability_artifacts
    rebuilds = 0

    def recording_rebuild(*args, **kwargs):
        nonlocal rebuilds
        rebuilds += 1
        return original_prepare(*args, **kwargs)

    monkeypatch.setattr(probability_engine, "prepare_probability_artifacts", recording_rebuild)
    _, _, _, action = resolve_probability_artifacts(
        revised,
        cached_targets=targets,
        cached_oof=oof,
        cached_contract=contract,
        spec=spec,
        formal_runtime_required=False,
    )
    assert action == "FULL_REBUILD_HISTORY_CHANGED"
    assert rebuilds == 1


@pytest.mark.parametrize("mismatch", ["probability_spec", "runtime"])
def test_probability_artifact_contract_rejects_spec_or_runtime_mismatch(mismatch) -> None:
    state = _artifact_state(40)
    spec = _artifact_spec()
    targets, oof = probability_engine.prepare_probability_artifacts(
        state, spec=spec, formal_runtime_required=False
    )
    contract = build_probability_artifact_contract(
        state,
        targets,
        oof,
        spec=spec,
        formal_runtime_required=False,
    )
    contract = copy.deepcopy(contract)
    if mismatch == "probability_spec":
        contract["probability_spec"]["training_min"] += 1
    else:
        contract["runtime"]["scikit-learn"] = "0.0.0"

    with pytest.raises(ProbabilityArtifactContractError, match=mismatch):
        validate_probability_artifact_contract(
            targets,
            oof,
            contract,
            spec=spec,
            formal_runtime_required=False,
        )


def test_rolling_intercept_calibration_and_clipping() -> None:
    raw = np.linspace(0.05, 0.95, 100)
    y = (raw > 0.55).astype(int)
    intercept = fit_intercept(raw, y)
    assert np.isfinite(intercept)
    assert np.mean([apply_intercept(value, intercept) for value in raw]) == pytest.approx(
        y.mean(), abs=1e-10
    )
    p = apply_intercept(1000, 1000)
    assert p == 1 - 1e-6


def test_exact_ece_uses_51_51_50_50_50() -> None:
    labels = np.tile([0, 1], 126)
    probs = np.linspace(0.001, 0.999, 252)
    dates = pd.date_range("2020-01-01", periods=252, freq="D")
    actual = exact_ece_252(labels, probs, dates)
    order = np.argsort(probs, kind="stable")
    cursor = 0
    expected = 0.0
    for size in [51, 51, 50, 50, 50]:
        idx = order[cursor : cursor + size]
        expected += size / 252 * abs(probs[idx].mean() - labels[idx].mean())
        cursor += size
    assert actual == pytest.approx(expected)


def test_brier_acceptance_gate() -> None:
    labels = np.tile([0, 1], 126)
    published = labels * 0.98 + (1 - labels) * 0.02
    base = np.full(252, 0.5)
    frame = pd.DataFrame(
        {
            "prediction_date": pd.date_range("2020-01-01", periods=252),
            "label": labels,
            "published_probability": published,
            "base_rate_at_prediction": base,
        }
    )
    result = acceptance_metrics(frame)
    assert result["accepted"] is True
    assert result["brier_skill"] > 0.02


def _event(
    status: str, model: str, p=None, base=None, uplift=None, kind=None, valid=None, text="x"
):
    if model == "BASE_RATE_ONLY":
        raw, method, samples, positive, negative, intercept = (
            None,
            "NOT_APPLICABLE",
            0,
            0,
            0,
            None,
        )
    elif model == "CALIBRATED_MODEL":
        raw, method, samples, positive, negative, intercept = (
            p,
            "ROLLING_INTERCEPT_252",
            40,
            20,
            20,
            0.0,
        )
    else:
        raw, method, samples, positive, negative, intercept = (None,) * 6
    return {
        "event_status": status,
        "model_status": model,
        "probability_kind": kind,
        "raw_probability": raw,
        "probability": p,
        "base_rate": base,
        "uplift": uplift,
        "calibration_method": method,
        "calibration_samples": samples,
        "calibration_positive": positive,
        "calibration_negative": negative,
        "intercept_b": intercept,
        "valid_through_session": valid,
        "interpretation": text,
    }


def test_outlook_probability_base_rate_uplift_relation_and_tie_order() -> None:
    events = {event: _event("NOT_APPLICABLE", "NOT_RUN") for event in EVENT_ORDER}
    events["acute_front_stress_5d"] = _event(
        "ELIGIBLE", "CALIBRATED_MODEL", 0.30, 0.20, 0.10, "FEATURE_CONDITIONAL", "2025-01-10"
    )
    events["front_inversion_5d"] = _event(
        "ELIGIBLE", "CALIBRATED_MODEL", 0.25, 0.15, 0.10, "FEATURE_CONDITIONAL", "2025-01-10"
    )
    assert events["acute_front_stress_5d"]["uplift"] == pytest.approx(
        events["acute_front_stress_5d"]["probability"]
        - events["acute_front_stress_5d"]["base_rate"]
    )
    assert outlook_answer("OK", events) == "acute_front_stress_5d"


def test_daily_output_rejects_probability_arithmetic_mismatch() -> None:
    row = base_state_frame(1).iloc[0].copy()
    row["outlook_answer"] = "UNKNOWN"
    events = {
        event: _event(
            "UNOBSERVABLE",
            "NOT_RUN",
            text="当前输入不足，无法观察该问题",
        )
        for event in EVENT_ORDER
    }
    valid = build_daily_output(row, events, manifest_hash="sha256:" + "0" * 64)
    event = valid["probability_judgment"]["acute_front_stress_5d"]
    event.update(
        {
            "event_status": "ELIGIBLE",
            "model_status": "BASE_RATE_ONLY",
            "probability_kind": "HISTORICAL_REFERENCE",
            "raw_probability": None,
            "probability": 0.42,
            "base_rate": 0.31,
            "uplift": 0.0,
            "calibration_method": "NOT_APPLICABLE",
            "calibration_samples": 0,
            "calibration_positive": 0,
            "calibration_negative": 0,
            "intercept_b": None,
            "valid_through_session": "2025-01-10",
            "interpretation": "当前只使用同类历史发生率，特征模型未提供增量判断",
        }
    )
    with pytest.raises(ValueError, match="probability == base_rate"):
        validate_daily_output(valid)


def test_outlook_base_rate_only_and_not_applicable() -> None:
    events = {event: _event("NOT_APPLICABLE", "NOT_RUN") for event in EVENT_ORDER}
    assert outlook_answer("OK", events) == "NOT_APPLICABLE"
    events["carry_environment_recovers_10d"] = _event(
        "ELIGIBLE", "BASE_RATE_ONLY", 0.2, 0.2, 0.0, "HISTORICAL_REFERENCE", "2025-01-10"
    )
    assert outlook_answer("OK", events) == "BASE_RATE_ONLY"


def test_event_json_truth_table_accepts_only_legal_combinations() -> None:
    resolver_schema = load_schema()
    base = _event(
        "ELIGIBLE",
        "BASE_RATE_ONLY",
        0.2,
        0.2,
        0.0,
        "HISTORICAL_REFERENCE",
        "2025-01-10",
        "当前只使用同类历史发生率，特征模型未提供增量判断",
    )
    # Validate via the full schema's event reference using a minimal wrapper.
    wrapper = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": resolver_schema["$defs"],
        "$ref": "#/$defs/event",
    }
    jsonschema.Draft202012Validator(wrapper, format_checker=jsonschema.FormatChecker()).validate(
        base
    )
    illegal = copy.deepcopy(base)
    illegal["model_status"] = "CALIBRATED_MODEL"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(
            wrapper, format_checker=jsonschema.FormatChecker()
        ).validate(illegal)
