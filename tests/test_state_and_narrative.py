from __future__ import annotations

import numpy as np
import pandas as pd
from conftest import base_state_frame

from matvix.constants import EVENT_ORDER
from matvix.dashboard import render_dashboard
from matvix.narrative import (
    build_narrative,
    rank_evidence,
    structural_triggers,
    what_changes_the_view,
)
from matvix.narrative.templates import basis30_market_story
from matvix.output import build_daily_output
from matvix.state.ontology import add_state_predicates_and_answers, at_least_k_true, tri_and, tri_or
from matvix.state.scores import PERCENTILE_INPUTS, add_percentiles_and_scores
from matvix.state.transitions import apply_phase_hysteresis


def test_three_valued_logic() -> None:
    assert tri_and(True, None) is None
    assert tri_and(False, None) is False
    assert tri_or(False, None) is None
    assert tri_or(True, None) is True
    assert at_least_k_true([True, True, None, False, False], 3) is None
    assert at_least_k_true([True, True, True, None, None], 3) is True
    assert at_least_k_true([True, False, False, False, None], 3) is False


def test_persistent_now_window_includes_today_and_missing_is_not_false() -> None:
    frame = base_state_frame(6)
    frame["persistence_score"] = [10, 80, np.nan, 80, 10, 80]
    frame["baseline_score"] = [10, 70, 70, 70, 10, 70]
    out = add_state_predicates_and_answers(frame)
    # On final date t-4...t has true, unknown, true, false, true => true (3 known TRUE).
    assert out.iloc[-1]["persistent_now"] is True
    # Earlier window with only two TRUE and one UNKNOWN cannot be forced to false.
    assert out.iloc[3]["persistent_now"] is None


def test_recent_stress_window_includes_today() -> None:
    frame = base_state_frame(10)
    frame["baseline_score"] = 20.0
    frame.loc[9, "baseline_score"] = 75.0
    out = add_state_predicates_and_answers(frame)
    assert out.iloc[9]["recent_stress"] is True


def test_acute_and_front_localized_are_orthogonal_axes() -> None:
    frame = base_state_frame(10)
    frame.loc[9, ["shock_score", "front_confirmation_count", "persistence_score"]] = [90, 2, 40]
    frame.loc[9, "hard_acute"] = True
    out = add_state_predicates_and_answers(frame)
    assert out.iloc[9]["shock_answer"] == "ACUTE"
    assert out.iloc[9]["persistence_answer"] == "FRONT_LOCALIZED"
    assert out.iloc[9]["raw_phase"] == "ACUTE_FRONT_STRESS"


def test_persistent_and_repair_can_coexist() -> None:
    frame = base_state_frame(12)
    frame.loc[7:11, ["persistence_score", "baseline_score"]] = [80, 75]
    frame.loc[10:11, "repair_score"] = 80
    frame.loc[10, "shock_score"] = 70
    frame.loc[11, "shock_score"] = 60
    frame.loc[11, "p_d5_fvol_30_93"] = 0.4
    frame.loc[11, "hard_acute"] = False
    out = add_state_predicates_and_answers(frame)
    assert out.iloc[-1]["persistence_answer"] == "PERSISTENT"
    assert out.iloc[-1]["repair_answer"] == "CONFIRMED"
    assert out.iloc[-1]["raw_phase"] == "REPAIR_IN_PROGRESS"


def test_phase_priority_hard_acute_over_repair() -> None:
    frame = base_state_frame(12)
    frame.loc[10:11, "repair_score"] = 80
    frame.loc[10, "shock_score"] = 70
    frame.loc[11, "shock_score"] = 90
    frame.loc[11, "front_confirmation_count"] = 2
    frame.loc[11, "hard_acute"] = True
    out = add_state_predicates_and_answers(frame)
    assert out.iloc[-1]["raw_phase"] == "ACUTE_FRONT_STRESS"


def test_phase_hysteresis_two_day_candidate() -> None:
    frame = pd.DataFrame(
        {
            "raw_phase": ["CARRY_SUPPORTIVE_LOW_STRESS", "MIXED_TRANSITION", "MIXED_TRANSITION"],
            "hard_acute": [False, False, False],
            "shock_score": [20.0, 45.0, 45.0],
        }
    )
    out = apply_phase_hysteresis(frame)
    assert out["phase"].tolist() == [
        "CARRY_SUPPORTIVE_LOW_STRESS",
        "CARRY_SUPPORTIVE_LOW_STRESS",
        "MIXED_TRANSITION",
    ]
    assert out.loc[1, "candidate_phase"] == "MIXED_TRANSITION"
    assert out.loc[1, "candidate_streak"] == 1


def test_acute_exit_requires_two_consecutive_release_days() -> None:
    frame = pd.DataFrame(
        {
            "raw_phase": ["ACUTE_FRONT_STRESS", "PRESSURE_BUILDING", "PRESSURE_BUILDING"],
            "hard_acute": [True, False, False],
            "shock_score": [90.0, 70.0, 70.0],
        }
    )
    out = apply_phase_hysteresis(frame)
    assert out["phase"].tolist() == [
        "ACUTE_FRONT_STRESS",
        "ACUTE_FRONT_STRESS",
        "PRESSURE_BUILDING",
    ]


def test_acute_exit_streak_counts_release_condition_not_raw_phase_identity() -> None:
    frame = pd.DataFrame(
        {
            "raw_phase": ["ACUTE_FRONT_STRESS", "PRESSURE_BUILDING", "MIXED_TRANSITION"],
            "hard_acute": [True, False, False],
            "shock_score": [90.0, 70.0, 60.0],
        }
    )
    out = apply_phase_hysteresis(frame)
    assert out["phase"].tolist() == ["ACUTE_FRONT_STRESS", "ACUTE_FRONT_STRESS", "MIXED_TRANSITION"]
    assert out.loc[1, "candidate_streak"] == 1


def test_repair_below_building_threshold_is_inactive_despite_unknown_recent_stress() -> None:
    frame = base_state_frame(10)
    frame["baseline_score"] = 20.0
    frame["hard_acute"] = pd.Series([False] * len(frame), dtype="object")
    frame.loc[0, "baseline_score"] = np.nan
    frame.loc[0, "hard_acute"] = None
    frame.loc[9, "repair_score"] = 59.0
    out = add_state_predicates_and_answers(frame)
    assert out.loc[9, "recent_stress"] is None
    assert out.loc[9, "repair_answer"] == "INACTIVE"
    assert out.loc[9, "data_status"] == "OK"


def test_ok_status_never_publishes_an_unknown_current_state_answer() -> None:
    frame = base_state_frame(1)
    out = add_state_predicates_and_answers(frame)
    answer_columns = [
        "carry_answer",
        "shock_answer",
        "tail_answer",
        "persistence_answer",
        "repair_answer",
    ]
    assert out.loc[0, "data_status"] == "PARTIAL"
    assert out.loc[0, answer_columns].eq("UNKNOWN").all()
    assert pd.isna(out.loc[0, "baseline_score"])


def test_percentile_history_isolated_by_feature_methodology_signature() -> None:
    rows = 7
    frame = pd.DataFrame(index=range(rows))
    for source, _ in PERCENTILE_INPUTS.values():
        frame[source] = np.arange(1.0, rows + 1.0)
    frame["feature_methodology_signature"] = ["A", "A", "A", "B", "B", "B", None]
    frame["formal_vintage_eligible"] = True
    frame["vx_settles"] = [[20.0, 21.0]] * rows
    frame["vix9d_close"] = 19.0
    frame["vix_close"] = 20.0
    frame["vxcm30"] = 21.0
    frame["curve_inversion_share"] = 0.0
    frame["f4_f7_inversion_share"] = 0.0

    out = add_percentiles_and_scores(frame, reference_sessions=3, minimum_valid=2)

    assert pd.isna(out.loc[3, "p_d1_log_vix"])
    assert pd.isna(out.loc[4, "p_d1_log_vix"])
    assert out.loc[5, "p_d1_log_vix"] == 1.0
    assert pd.isna(out.loc[6, "p_d1_log_vix"])


def test_unknown_clears_candidate_and_recovery_bootstraps() -> None:
    frame = pd.DataFrame(
        {
            "raw_phase": [
                "MIXED_TRANSITION",
                "CARRY_SUPPORTIVE_LOW_STRESS",
                "UNKNOWN",
                "TAIL_RICH_QUIET_CURVE",
            ],
            "hard_acute": [False, False, np.nan, False],
            "shock_score": [40.0, 20.0, np.nan, 30.0],
        }
    )
    out = apply_phase_hysteresis(frame)
    assert out.loc[2, "phase"] == "UNKNOWN"
    assert out.loc[2, "candidate_streak"] == 0
    assert out.loc[3, "phase"] == "TAIL_RICH_QUIET_CURVE"


def test_driver_and_counter_ranking_is_deterministic() -> None:
    row = base_state_frame(1).iloc[0].copy()
    row["p_near_stress"] = 0.99
    row["p_d1_log_vix"] = 0.95
    row["p_skew"] = 0.90
    row["p_neg_front_slope30"] = 0.10
    drivers, counters, repair = rank_evidence(row)
    assert len(drivers) <= 3 and len(counters) <= 2 and len(repair) <= 3
    assert drivers[0]["evidence_id"] == "tail.skew_level"
    assert counters[0]["evidence_id"] == "carry.front_slope"
    assert all(
        set(item)
        == {"evidence_id", "feature", "raw_value", "percentile", "contribution", "meaning"}
        for item in drivers + counters
    )


def test_structural_triggers_only_computed_facts() -> None:
    row = base_state_frame(1).iloc[0].copy()
    row["vix9d_close"] = 22
    row["vix_close"] = 20
    row["ts12"] = -0.03
    row["p_cash_vix_oscillator"] = 0.95
    row["hard_acute"] = True
    triggers = structural_triggers(row)
    assert len(triggers) == 4


def test_narrative_traceability_and_no_structured_mutation() -> None:
    row = base_state_frame(1).iloc[0].copy()
    row["phase"] = "PRESSURE_BUILDING"
    row["carry_answer"] = "STRESSED"
    row["shock_answer"] = "HIGH"
    row["persistence_answer"] = "FRONT_LOCALIZED"
    row["tail_answer"] = "RICH"
    row["repair_answer"] = "BUILDING"
    row["p_near_stress"] = 0.95
    drivers, counters, _ = rank_evidence(row)
    before = row.copy(deep=True)
    events = {"x": {"event_status": "ELIGIBLE"}}
    text = build_narrative(
        row, drivers=drivers, counter_evidence=counters, events=events, outlook="BASE_RATE_ONLY"
    )
    pd.testing.assert_series_equal(row, before)
    assert "保险市场压力正在累积" in text
    assert "当前仅有同类历史发生率" in text
    for driver in drivers:
        assert driver["meaning"] in text


def test_basis30_story_distinguishes_spot_unwind_from_forward_repricing() -> None:
    spot_unwind = pd.Series({"d5_log_vxcm30": -0.02, "d5_log_vix": -0.10, "d5_basis30_eod": 0.08})
    forward_repricing = pd.Series(
        {"d5_log_vxcm30": 0.10, "d5_log_vix": 0.02, "d5_basis30_eod": 0.08}
    )
    assert "现货 VIX 更快回落" in basis30_market_story(spot_unwind)
    assert "30 日 VX 合成价抬升更快" in basis30_market_story(forward_repricing)


def test_narrative_includes_repair_evidence_and_structural_triggers() -> None:
    row = base_state_frame(10).iloc[-1].copy()
    row["p_neg_d5_log_vix"] = 0.92
    row["d5_log_vix"] = -0.12
    row["vix9d_close"] = 22.0
    row["vix_close"] = 20.0
    row["hard_acute"] = True
    _, _, repair = rank_evidence(row)
    text = build_narrative(
        row,
        drivers=[],
        counter_evidence=[],
        events={"x": {"event_status": "ELIGIBLE"}},
        outlook="BASE_RATE_ONLY",
    )
    assert repair[0]["meaning"] in text
    assert "VIX9D 高于 VIX" in text
    assert "急性硬确认成立" in text


def test_dashboard_shows_repair_triggers_and_curve_breadth_as_ratio() -> None:
    row = base_state_frame(10).iloc[-1].copy()
    row["session_date"] = pd.Timestamp("2025-01-02")
    row["f4_f7_inversion_share"] = 0.8
    row["p_neg_d5_log_vix"] = 0.92
    row["d5_log_vix"] = -0.12
    row["vix9d_close"] = 22.0
    row["vix_close"] = 20.0
    events = {
        event: {
            "event_status": "UNOBSERVABLE",
            "model_status": "NOT_RUN",
            "probability_kind": None,
            "probability": None,
            "base_rate": None,
            "uplift": None,
            "valid_through_session": None,
            "interpretation": "当前输入不足，无法观察该问题",
        }
        for event in EVENT_ORDER
    }
    payload = build_daily_output(row, events, manifest_hash="sha256:" + "0" * 64)
    dashboard = render_dashboard(payload)
    assert "修复证据" in dashboard and "VIX 五日边际回落" in dashboard
    assert "结构触发" in dashboard and "VIX9D 高于 VIX" in dashboard
    assert "三个 F4–F7 相邻期限段中的倒挂占比为 80%" in dashboard
    assert "f4_f7_inversion_share · p=0.800" not in dashboard


def test_what_changes_has_one_to_three_items() -> None:
    for phase in ["UNKNOWN", "ACUTE_FRONT_STRESS", "REPAIR_IN_PROGRESS", "MIXED_TRANSITION"]:
        items = what_changes_the_view(phase)
        assert 1 <= len(items) <= 3


def test_narrative_explains_hysteresis_when_published_phase_differs_from_candidate() -> None:
    row = base_state_frame(1).iloc[0].copy()
    row["phase"] = "REPAIR_IN_PROGRESS"
    row["repair_answer"] = "BUILDING"
    row["candidate_phase"] = "MIXED_TRANSITION"
    row["candidate_streak"] = 1

    narrative = build_narrative(
        row,
        drivers=[],
        counter_evidence=[],
        events={},
        outlook="UNKNOWN",
    )

    assert "高压后的修复阶段仍在进行" in narrative
    assert "当日原始证据指向 MIXED_TRANSITION，已连续 1 日" in narrative
    assert "发布阶段暂时保留为 REPAIR_IN_PROGRESS" in narrative
