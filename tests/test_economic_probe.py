from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from matvix.economic_probe import (
    _economic_figures,
    adapt_weather,
    build_economic_probe,
    build_probe_ledger,
    build_v3_economic_probe,
    classify_probe,
    parse_yahoo_chart,
    target_asset,
    write_economic_probe_outputs,
)


def _weather() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "session_date": pd.to_datetime(
                ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
            ),
            "data_status": ["OK", "OK", "OK", "OK"],
            "carry_answer": ["SUPPORTIVE", "MIXED", "MIXED", "MIXED"],
            "shock_answer": ["CALM", "CALM", "CALM", "CALM"],
            "persistence_answer": ["NORMAL", "NORMAL", "DIFFUSING", "PERSISTENT"],
        }
    )


def _prices() -> pd.DataFrame:
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
    records = []
    for ticker, values in {
        "SVXY": [100.0, 100.0, 110.0, 110.0],
        "SGOV": [100.0, 100.0, 100.0, 100.0],
        "VXZ": [100.0, 100.0, 100.0, 100.0],
    }.items():
        records.extend(
            {"session_date": session, "ticker": ticker, "adjusted_open": value}
            for session, value in zip(dates, values, strict=True)
        )
    return pd.DataFrame(records)


def test_shared_adapter_and_fixed_probe_precedence() -> None:
    weather = adapt_weather(_weather(), "V2")

    assert target_asset(weather.iloc[0], "short") == ("SHORT_ALLOWED", "SVXY")
    assert target_asset(weather.iloc[0], "long") == ("DEFENSIVE", "SGOV")
    assert target_asset(weather.iloc[2], "combined") == (
        "MID_DIFFUSION_CONFIRMED",
        "VXZ",
    )
    assert target_asset(weather.iloc[3], "combined") == ("DEFENSIVE", "SGOV")


def test_open_to_open_execution_cost_and_switch_are_hand_calculable() -> None:
    weather = adapt_weather(_weather(), "V2")
    ledger = build_probe_ledger(weather, _prices(), probe="short", initial_nav=10_000.0)

    first = ledger.iloc[0]
    assert first["signal_session"] == pd.Timestamp("2024-01-02")
    assert first["execution_session"] == pd.Timestamp("2024-01-03")
    assert first["return_through_session"] == pd.Timestamp("2024-01-04")
    assert first["turnover"] == 1.0
    assert first["cost"] == pytest.approx(5.0)
    assert first["gross_return"] == pytest.approx(0.10)
    assert first["nav"] == pytest.approx(9_995.0 * 1.10)

    switched = ledger.iloc[1]
    assert switched["target_asset"] == "SGOV"
    assert switched["turnover"] == 2.0
    assert switched["cost"] == pytest.approx(first["nav"] * 0.001)
    assert switched["gross_return"] == 0.0


def test_yahoo_adjusted_open_uses_adjusted_close_over_raw_close() -> None:
    timestamp = int(pd.Timestamp("2024-01-02", tz="UTC").timestamp())
    payload = {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {"exchangeTimezoneName": "UTC"},
                    "timestamp": [timestamp],
                    "indicators": {
                        "quote": [
                            {
                                "open": [8.0],
                                "high": [11.0],
                                "low": [7.0],
                                "close": [10.0],
                                "volume": [100],
                            }
                        ],
                        "adjclose": [{"adjclose": [5.0]}],
                    },
                    "events": {"splits": {}, "dividends": {}},
                }
            ],
        }
    }

    frame = parse_yahoo_chart(payload, "SVXY")

    assert frame.iloc[0]["adjustment_factor"] == pytest.approx(0.5)
    assert frame.iloc[0]["adjusted_open"] == pytest.approx(4.0)


def test_probe_classification_preserves_return_risk_tradeoffs() -> None:
    v1 = {"final_nav": 100.0, "max_drawdown": -0.10, "worst_rolling_20d": -0.05}

    assert classify_probe(
        v1,
        {"final_nav": 110.0, "max_drawdown": -0.08, "worst_rolling_20d": -0.05},
    ) == "POSITIVE"
    assert classify_probe(
        v1,
        {"final_nav": 110.0, "max_drawdown": -0.12, "worst_rolling_20d": -0.05},
    ) == "MIXED"
    assert classify_probe(
        v1,
        {"final_nav": 90.0, "max_drawdown": -0.12, "worst_rolling_20d": -0.04},
    ) == "NEGATIVE"
    assert classify_probe(v1, v1, eligible=False) == "NOT_ELIGIBLE"


def test_missing_adjusted_open_is_a_data_failure() -> None:
    prices = _prices()
    prices.loc[
        prices["ticker"].eq("SVXY") & prices["session_date"].eq(pd.Timestamp("2024-01-04")),
        "adjusted_open",
    ] = np.nan

    with pytest.raises(ValueError, match="Missing adjusted-open"):
        build_probe_ledger(adapt_weather(_weather(), "V2"), prices, probe="short")


def test_synthetic_end_to_end_probe_writes_one_ledger_json_and_html(tmp_path) -> None:
    dates = pd.bdate_range("2024-01-02", periods=35)
    states = pd.DataFrame(
        {
            "session_date": dates,
            "data_status": "OK",
            "carry_answer": "MIXED",
            "shock_answer": "CALM",
            "persistence_answer": "NORMAL",
        }
    )
    states.loc[5:8, "persistence_answer"] = "DIFFUSING"
    prices = pd.concat(
        [
            pd.DataFrame(
                {
                    "session_date": dates,
                    "ticker": ticker,
                    "adjusted_open": 100.0
                    * np.cumprod(np.full(len(dates), 1.0 + daily_return)),
                }
            )
            for ticker, daily_return in {"SVXY": 0.001, "SGOV": 0.0001, "VXZ": 0.0003}.items()
        ],
        ignore_index=True,
    )
    station = {
        "dimensions": {
            name: {"status": "PASS"}
            for name in ("DATA", "TENOR", "STATE_TIMING", "PROBABILITY_INTEGRITY")
        }
    }

    ledger, report = build_economic_probe(
        v1_states=states,
        v2_states=states,
        prices=prices,
        source_manifest={"batch_id": "synthetic"},
        station_summary=station,
    )
    outputs = write_economic_probe_outputs(ledger, report, tmp_path)

    assert len(ledger) == 2 * 3 * (len(dates) - 2)
    assert set(report["metrics"]) == {"V1", "V2"}
    assert report["classifications"] == {
        "short": "MIXED",
        "long": "MIXED",
        "combined": "MIXED",
    }
    assert set(outputs) == {"ledger", "report", "html"}
    assert all(path.is_file() for path in outputs.values())
    html = outputs["html"].read_text(encoding="utf-8")
    for title in (
        "V1/V2 三个固定探针净值",
        "Underwater 回撤",
        "滚动 20-session 收益",
        "最差 20 个 SVXY 日的实际资产暴露",
        "状态与 Combined 持仓时间轴",
        "调仓、turnover 与成本瀑布",
        "每个 DIFFUSING 事件簇的 VXZ 相对 SGOV 收益",
    ):
        assert title in html

    timeline = dict(_economic_figures(ledger, report))["状态与 Combined 持仓时间轴"]
    assert len(timeline.data) == 2
    assert all(len(trace.z) == 2 for trace in timeline.data)
    assert all(len(row) == len(dates) - 2 for trace in timeline.data for row in trace.z)

    station["dimension_order"] = list(station["dimensions"])
    shadow = pd.DataFrame(columns=[
        "prediction_date", "published_probability", "base_rate_at_prediction",
        "calibration_method",
    ])
    v3_ledger, v3_report = build_v3_economic_probe(
        v2_states=states, v3_states=states, shadow_oof=shadow, prices=prices,
        source_manifest={"batch_id": "synthetic"}, station_summary=station,
        replay_evidence={},
    )
    assert v3_report["classifications"] == {
        "short": "MIXED", "long": "POSITIVE", "combined": "POSITIVE",
    }
    assert v3_report["frozen_v3_gates"]["long_daily_exact"] is True
    assert "unqualified_fragility_veto_shadow" in v3_ledger
