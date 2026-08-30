from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "analysis" / "e15_rolling_intercept_calibration.py"
SPEC = importlib.util.spec_from_file_location("e15_rolling_intercept_calibration", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
research = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = research
SPEC.loader.exec_module(research)


def _panel(count: int = 80) -> pd.DataFrame:
    origins = pd.bdate_range("2024-01-02", periods=count)
    forecast = pd.to_datetime(origins, utc=True) + pd.Timedelta(hours=14, minutes=20)
    labels = (np.arange(count) % 4 == 0).astype(int)
    h3_probability = np.clip(0.12 + 0.16 * labels + 0.03 * np.sin(np.arange(count)), 0.02, 0.8)
    return pd.DataFrame(
        {
            "origin_session": origins,
            "forecast_as_of": forecast,
            "outcome_available_at": forecast + pd.Timedelta(days=6),
            "evaluation_cohort": "SYNTHETIC",
            "label": labels,
            "label_status": "OBSERVED",
            "episode_id": np.where(
                labels == 1, "E" + pd.Series(np.arange(count)).astype(str), None
            ),
            "b0_probability": 0.20,
            "b1_probability": 0.18,
            "b1_genuine": True,
            "h3_probability": h3_probability,
            "h3_genuine": True,
            "h3_state": "EMITTED",
        }
    )


def test_completed_training_is_prior_mature_genuine_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(research, "CALIBRATION_MAX", 12)
    panel = _panel()
    current = panel.iloc[-1]
    excluded_origin = panel.iloc[-5]["origin_session"]
    panel.loc[panel.index[-5], "outcome_available_at"] = pd.Timestamp(
        current["forecast_as_of"]
    ) + pd.Timedelta(days=1)
    panel.loc[panel.index[-6], "h3_genuine"] = False

    training = research.completed_calibration_training(panel, current)

    assert len(training) <= 12
    assert excluded_origin not in set(training["origin_session"])
    assert training["origin_session"].lt(current["origin_session"]).all()
    assert training["outcome_available_at"].le(current["forecast_as_of"]).all()
    assert training["h3_genuine"].all()


def test_rolling_intercept_replays_and_preserves_warmup_and_abstention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(research, "CALIBRATION_MAX", 20)
    monkeypatch.setattr(research, "CALIBRATION_MIN_POSITIVE", 2)
    monkeypatch.setattr(research, "CALIBRATION_MIN_NEGATIVE", 2)
    panel = _panel()
    panel.loc[panel.index[-1], "h3_genuine"] = False
    panel.loc[panel.index[-1], "h3_state"] = "ABSTAIN_DATA"

    ledger = research.build_rolling_intercept_ledger(panel)

    emitted = ledger.loc[ledger["ri_state"].eq("RI_EMITTED")]
    assert not emitted.empty
    row = emitted.iloc[-1]
    expected = research.apply_intercept(row["h3_probability"], row["ri_intercept_b"])
    assert row["ri_probability"] == pytest.approx(expected, abs=1e-12)
    assert row["ri_calibration_samples"] <= 20
    assert ledger["ri_state"].eq("IDENTITY_WARMUP").any()
    warmup = ledger.loc[ledger["ri_state"].eq("IDENTITY_WARMUP")]
    assert np.array_equal(warmup["ri_probability"], warmup["h3_probability"])
    final = ledger.iloc[-1]
    assert final["ri_state"] == "ABSTAIN_H3"
    assert final["ri_probability"] == final["h3_probability"]
    assert research.evaluate_causal_replay(ledger)["passed"] is True


def test_causal_replay_rejects_post_forecast_training_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(research, "CALIBRATION_MAX", 20)
    monkeypatch.setattr(research, "CALIBRATION_MIN_POSITIVE", 2)
    monkeypatch.setattr(research, "CALIBRATION_MIN_NEGATIVE", 2)
    ledger = research.build_rolling_intercept_ledger(_panel())
    index = ledger.index[ledger["ri_state"].eq("RI_EMITTED")][-1]
    ledger.loc[index, "ri_training_latest_outcome_available_at"] = ledger.loc[
        index, "forecast_as_of"
    ] + pd.Timedelta(days=1)

    result = research.evaluate_causal_replay(ledger)

    assert result["passed"] is False
    assert any("unavailable" in item for item in result["violations"])


@pytest.mark.parametrize(
    ("gates", "expected"),
    [
        (
            {
                "CAUSAL_REPLAY": False,
                "CALIBRATION_REPAIR": True,
                "PROPER_SCORE": True,
                "RESOLUTION_RETENTION": True,
            },
            "INVALID_EVALUATION",
        ),
        (
            {
                "CAUSAL_REPLAY": True,
                "CALIBRATION_REPAIR": False,
                "PROPER_SCORE": True,
                "RESOLUTION_RETENTION": True,
            },
            "CALIBRATION_REPAIR_NOT_ESTABLISHED",
        ),
        (
            {
                "CAUSAL_REPLAY": True,
                "CALIBRATION_REPAIR": True,
                "PROPER_SCORE": False,
                "RESOLUTION_RETENTION": True,
            },
            "CALIBRATION_REPAIR_REJECTED_FOR_INFORMATION_LOSS",
        ),
        (
            {
                "CAUSAL_REPLAY": True,
                "CALIBRATION_REPAIR": True,
                "PROPER_SCORE": True,
                "RESOLUTION_RETENTION": True,
            },
            "ROLLING_INTERCEPT_CALIBRATION_SUPPORTED",
        ),
    ],
)
def test_frozen_gate_precedence(gates: dict[str, bool], expected: str) -> None:
    assert research.verdict_from_gates(gates) == expected


def test_formal_outputs_require_frozen_draw_count() -> None:
    with pytest.raises(research.ResearchError, match="exactly 5000"):
        research.run(PROJECT_ROOT, draws=20, write_outputs=True)


def test_real_artifact_smoke_is_causal_and_does_not_write() -> None:
    required = tuple(PROJECT_ROOT / path for path in research.FROZEN_SHA256)
    if not all(path.exists() for path in required):
        pytest.skip("Ignored local H3 ledgers are not present")

    evidence = research.run(PROJECT_ROOT, draws=30, write_outputs=False)

    assert evidence["causal_replay"]["passed"] is True
    assert evidence["cohort"]["formal_origins"] > 0
    assert evidence["verdict"] in {
        "CALIBRATION_REPAIR_NOT_ESTABLISHED",
        "CALIBRATION_REPAIR_REJECTED_FOR_INFORMATION_LOSS",
        "ROLLING_INTERCEPT_CALIBRATION_SUPPORTED",
    }
    assert evidence["authority"] == {
        "research_only": True,
        "v3_change": False,
        "prospective_change": False,
        "position_order_or_trading": False,
    }
