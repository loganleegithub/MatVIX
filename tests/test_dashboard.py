from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from typing import Any

from matvix.dashboard import AXIS_ORDER, EVENT_ORDER, render_dashboard


def _event(
    probability: float | None,
    base_rate: float | None,
    *,
    model_status: str = "CALIBRATED_MODEL",
    event_status: str = "ELIGIBLE",
) -> dict[str, Any]:
    uplift = None if probability is None or base_rate is None else probability - base_rate
    return {
        "event_status": event_status,
        "model_status": model_status,
        "probability_kind": (
            "FEATURE_CONDITIONAL"
            if model_status == "CALIBRATED_MODEL"
            else "HISTORICAL_REFERENCE"
        ),
        "probability": probability,
        "base_rate": base_rate,
        "uplift": uplift,
        "valid_through_session": "2026-08-25" if probability is not None else None,
        "interpretation": "测试解释",
    }


def _snapshot() -> dict[str, Any]:
    return {
        "session_date": "2026-08-18",
        "decision_as_of": "2026-08-19T09:20:00-04:00",
        "data_status": "OK",
        "market_story": {
            "headline": "市场证据分化，处于过渡状态。",
            "phase": "MIXED_TRANSITION",
            "pressure_level": "WATCH",
            "direction": "RISING",
            "baseline_score": 40.4,
            "answers": {
                "repair": "INACTIVE",
                "tail": "NORMAL",
                "shock": "BUILDING",
                "outlook": "NO_STRONG_EDGE",
                "carry": "SUPPORTIVE",
                "persistence": "MIXED",
            },
            "scores": {
                "repair": 45.7,
                "tail_price": 58.4,
                "shock": 50.3,
                "carry_risk": 7.7,
                "persistence": 56.4,
            },
            "drivers": [
                {
                    "evidence_id": "shock.vix_change_1d",
                    "feature": "d1_log_vix",
                    "raw_value": 0.042,
                    "percentile": 0.786,
                    "contribution": 0.017,
                    "meaning": "VIX 单日重定价速度偏高",
                }
            ],
            "counter_evidence": [
                {
                    "evidence_id": "carry.front_slope",
                    "feature": "front_slope30",
                    "raw_value": 0.147,
                    "percentile": 0.019,
                    "contribution": -0.065,
                    "meaning": "前端 VX 曲线仍相对陡峭，carry 结构未明显受损",
                }
            ],
            "repair_evidence": [],
            "structural_triggers": [],
            "what_changes_the_view": ["任一非 mixed 的 raw phase 连续两日成立"],
            "narrative": "风险升温与结构缓冲并存。",
        },
        "probability_judgment": {
            "fast_repair_5d": {
                **_event(None, None, model_status="NOT_RUN", event_status="NOT_APPLICABLE"),
                "probability_kind": None,
            },
            "broad_persistent_stress_20d": _event(
                0.109, 0.109, model_status="BASE_RATE_ONLY"
            ),
            "front_inversion_5d": _event(0.040, 0.100),
            "acute_front_stress_5d": _event(0.118, 0.127),
        },
        "observations": {
            "vix9d_close": 13.59,
            "vix_close": 15.84,
            "vix3m_close": 19.27,
            "vix6m_close": 21.37,
            "vx_contract_ids": ["F1", "F2", "F3", "F4", "F5", "F6", "F7"],
            "vx_settles": [15.9, 18.2, 19.7, 20.4, 20.5, 21.6],
        },
        "diagnostics": {"hard_acute": False},
    }


@lru_cache(maxsize=1)
def _rendered() -> str:
    return render_dashboard(_snapshot())


def test_trader_dashboard_uses_fixed_business_order_and_separates_repair() -> None:
    dashboard = _rendered()

    axis_positions = [dashboard.index(f'data-axis="{axis}"') for axis in AXIS_ORDER]
    assert axis_positions == sorted(axis_positions)
    assert dashboard.index("Carry 是否受损？") < dashboard.index("短端是否抢险？")
    assert dashboard.index("短端是否抢险？") < dashboard.index("尾部是否昂贵？")
    assert dashboard.index("尾部是否昂贵？") < dashboard.index("压力是否扩散？")
    assert dashboard.index("压力是否扩散？") < dashboard.index("高压后是否修复？")
    assert 'class="axis-card repair-axis"' in dashboard
    assert "Repair · 修复证据分" in dashboard
    assert "结构稳定度 = 100 − CarryRisk，仅作反向展示，不是新模型或独立信号" in dashboard
    assert "结构稳定度 92.3" in dashboard


def test_trader_dashboard_explains_state_and_probability_qualification() -> None:
    dashboard = _rendered()

    assert "风险正在升温，结构性压力尚未确认" in dashboard
    assert "升温证据与结构缓冲同时存在" in dashboard
    assert "暂无强概率优势" in dashboard
    assert "仅历史频率 · 不是当前信号" in dashboard
    event_positions = [dashboard.index(f'data-event="{event}"') for event in EVENT_ORDER]
    assert event_positions == sorted(event_positions)
    assert dashboard.count("data-summary-event=") == 3
    assert "不适用 / 状态已存在" in dashboard
    repair_marker = dashboard.index('data-event="fast_repair_5d"')
    repair_card = dashboard[repair_marker : repair_marker + 900]
    assert "不适用 / 状态已存在" in repair_card
    assert '<div class="probability">0.0%</div>' not in repair_card


def test_trader_dashboard_exposes_interaction_and_http_polling_hooks() -> None:
    dashboard = _rendered()

    assert 'data-dashboard-version="trader-v1"' in dashboard
    assert 'id="runtime-status"' in dashboard
    assert 'data-status-endpoint="/api/status"' in dashboard
    assert 'data-open-panel="conflict-panel"' in dashboard
    assert 'data-open-panel="quant-panel"' in dashboard
    assert 'id="conflict-panel"' in dashboard and 'id="quant-panel"' in dashboard
    assert "window.MatVIXDashboard" in dashboard
    assert "startStatusPolling" in dashboard
    assert "latest_snapshot_session" in dashboard
    assert "last_good_session" in dashboard
    assert "dashboardRevision" in dashboard
    assert "DASHBOARD_RENDER_FAILED" in dashboard
    assert "待展示截面" in dashboard
    assert "新截面可用，刷新页面查看" in dashboard
    assert "matvix:status" in dashboard
    assert "data-live-field=\"session_date\"" in dashboard
    assert "market-weather-gauge" in dashboard
    assert "short-temperature-gauge" in dashboard
    assert "composite-judgment-gauge" in dashboard
    assert "structure-stability-gauge" in dashboard


def test_triad_driver_labels_do_not_borrow_evidence_from_other_axes() -> None:
    snapshot = deepcopy(_snapshot())
    snapshot["market_story"]["drivers"] = [
        {
            "evidence_id": "tail_price.skew_level",
            "feature": "skew_close",
            "percentile": 0.9,
            "meaning": "尾部保险价格偏高",
        }
    ]
    snapshot["market_story"]["counter_evidence"] = [
        {
            "evidence_id": "tail_price.vvix_level",
            "feature": "vvix_close",
            "percentile": 0.2,
            "meaning": "波动率的波动率回落",
        }
    ]

    dashboard = render_dashboard(snapshot)

    triad = dashboard[dashboard.index('<section class="triad"') : dashboard.index(
        '<section class="axes-section"'
    )]
    assert "主要驱动：Shock 分量未进入全局证据榜" in triad
    assert "主要缓冲：Carry 分量未进入全局证据榜" in triad
    assert "SKEW" not in triad
    assert "VVIX" not in triad


def test_triad_uses_axis_specific_components_when_global_evidence_is_truncated() -> None:
    snapshot = deepcopy(_snapshot())
    snapshot["market_story"]["drivers"] = [
        {
            "evidence_id": "tail.skew_level",
            "feature": "skew_close",
            "percentile": 1.0,
            "meaning": "尾部价格",
        }
    ]
    snapshot["market_story"]["counter_evidence"] = []
    snapshot["diagnostics"]["component_contributions"] = [
        {
            "axis": "shock",
            "id": "shock.near_stress",
            "percentile": 1.0,
            "contribution": 0.050,
            "feature_refs": ["near_stress_log_ratio"],
        },
        {
            "axis": "shock",
            "id": "shock.vix_change_1d",
            "percentile": 1.0,
            "contribution": 0.045,
            "feature_refs": ["d1_log_vix"],
        },
        {
            "axis": "shock",
            "id": "shock.vvix_change_5d",
            "percentile": 1.0,
            "contribution": 0.040,
            "feature_refs": ["d5_log_vvix"],
        },
        {
            "axis": "carry_risk",
            "id": "carry.front_slope",
            "percentile": 0.0,
            "contribution": 0.0,
            "feature_refs": ["front_slope30"],
        },
        {
            "axis": "carry_risk",
            "id": "carry.basis",
            "percentile": 0.0,
            "contribution": 0.001,
            "feature_refs": ["basis30_eod"],
        },
    ]

    dashboard = render_dashboard(snapshot)
    triad = dashboard[dashboard.index('<section class="triad"') : dashboard.index(
        '<section class="axes-section"'
    )]

    assert "主要驱动：VIX9D / VIX · VIX · VVIX" in triad
    assert "主要缓冲：VX 曲线 · Basis" in triad
    assert "SKEW" not in triad


def test_base_rate_only_summary_does_not_become_a_feature_signal() -> None:
    snapshot = deepcopy(_snapshot())
    event = snapshot["probability_judgment"]["broad_persistent_stress_20d"]
    assert event["probability"] == event["base_rate"]

    dashboard = render_dashboard(snapshot)

    marker = dashboard.index('data-summary-event="broad_persistent_stress_20d"')
    card = dashboard[marker : marker + 900]
    assert "10.9%" in card
    assert "仅历史频率 · 不是当前信号" in card
