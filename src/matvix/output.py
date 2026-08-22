from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, cast

import jsonschema
import numpy as np
import pandas as pd

from matvix.calendar import decision_as_of
from matvix.config import project_root
from matvix.constants import (
    FEATURE_VERSION,
    MODEL_ID,
    PROBABILITY_VERSION,
    SCHEMA_VERSION,
    STATE_VERSION,
)
from matvix.narrative import (
    PHASE_HEADLINES,
    build_narrative,
    rank_evidence,
    structural_triggers,
    what_changes_the_view,
)
from matvix.state.scores import component_contributions

CORE_OBSERVATION_FIELDS = [
    "vix_open",
    "vix_high",
    "vix_low",
    "vix_close",
    "vix9d_close",
    "vix3m_close",
    "vix6m_close",
    "vvix_close",
    "skew_close",
    "spx_close",
    "vx_contract_ids",
    "vx_settles",
    "vx_days_to_final",
]

DIAGNOSTIC_FIELDS = [
    "ts12",
    "front_slope30",
    "vxcm30",
    "vxcm30_source_kind",
    "vxcm30_methodology",
    "basis30_eod",
    "ratio_9_30",
    "near_stress_log_ratio",
    "ratio_30_93",
    "medium_front_log_ratio",
    "fvar_9_30",
    "fvar_30_93",
    "fvar_93_184",
    "fvol_9_30",
    "fvol_30_93",
    "fvol_93_184",
    "curve_inversion_share",
    "front_curve_level",
    "f4_f7_level",
    "f4_f7_slope30",
    "f4_f7_inversion_share",
    "front_to_mid_log_ratio",
    "cash_vix_oscillator",
    "vix_atr14",
    "vix_atrp14",
    "vix_ema5",
    "vix_ema20",
    "vix_ema5_minus_20",
    "vix_rsi14",
    "vix_stochastic_k14",
    "vix_stochastic_d3",
    "vix_macd_12_26",
    "vix_macd_signal_9",
    "vix_macd_histogram",
    "vrp_ewma94",
    "vrp_percentile",
    "carry_compensation",
    "d1_log_vix",
    "d5_log_vix",
    "d5_log_vvix",
    "d5_log_vxcm30",
    "d5_front_slope30",
    "d5_basis30_eod",
    "d5_near_stress",
    "d5_skew",
    "d5_fvol_30_93",
    "d5_fvol_93_184",
    "d5_log_f4_f7_level",
    "d5_f4_f7_slope30",
    "d5_f4_f7_inversion_share",
    "d10_log_f4_f7_level",
    "d10_f4_f7_slope30",
    "d10_f4_f7_inversion_share",
    "p_f4_f7_level",
    "p_neg_f4_f7_slope30",
    "p_d5_log_f4_f7_level",
    "p_neg_d5_log_f4_f7_level",
    "p_d5_f4_f7_slope30",
    "p_neg_d5_f4_f7_slope30",
    "front_confirmation_count",
    "hard_acute",
    "persistent_day",
    "persistent_now",
    "recent_stress",
    "repair_confirmed",
    "feature_vintage_kind",
    "feature_methodology_signature",
    "pit_evidence",
    "formal_vintage_eligible",
    "front_curve_formal_vintage_eligible",
    "hard_acute_formal_vintage_eligible",
    "persistent_day_formal_vintage_eligible",
    "repair_confirmed_formal_vintage_eligible",
]


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        if value.tzinfo is None:
            return value.date().isoformat() if value == value.normalize() else value.isoformat()
        return value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def input_manifest_hash(rows: pd.DataFrame | Iterable[Mapping[str, Any]]) -> str:
    if isinstance(rows, pd.DataFrame):
        required = ["series_id", "session_date", "revision_id"]
        missing = [column for column in required if column not in rows.columns]
        if missing:
            raise ValueError(f"Input manifest columns missing: {missing}")
        records = rows[required].to_dict(orient="records")
    else:
        records = [
            {
                "series_id": row["series_id"],
                "session_date": row["session_date"],
                "revision_id": row["revision_id"],
            }
            for row in rows
        ]
    normalized = sorted(
        (
            str(record["series_id"]),
            pd.Timestamp(record["session_date"]).date().isoformat(),
            str(record["revision_id"]),
        )
        for record in records
    )
    encoded = json.dumps(normalized, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def feature_digest(row: pd.Series) -> str:
    record = {str(key): _json_value(value) for key, value in row.to_dict().items()}
    encoded = json.dumps(record, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode(
        "utf-8"
    )
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _int_or_zero(value: Any) -> int:
    if value is None or pd.isna(value):
        return 0
    return int(value)


def _mapping(row: pd.Series, fields: list[str]) -> dict[str, Any]:
    return {field: _json_value(row.get(field)) for field in fields if field in row.index}


def build_daily_output(
    row: pd.Series,
    probability_judgment: dict[str, dict[str, Any]],
    *,
    manifest_hash: str,
    issues: list[str] | None = None,
) -> dict[str, Any]:
    session = pd.Timestamp(row["session_date"]).normalize()
    data_status = str(row.get("data_status", "UNKNOWN"))
    drivers, counters, repair_evidence = rank_evidence(row) if data_status == "OK" else ([], [], [])
    outlook = str(row.get("outlook_answer", "UNKNOWN"))
    phase = str(row.get("phase", "UNKNOWN"))
    headline = PHASE_HEADLINES.get(phase, PHASE_HEADLINES["UNKNOWN"])
    narrative = build_narrative(
        row,
        drivers=drivers,
        counter_evidence=counters,
        events=probability_judgment,
        outlook=outlook,
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "model_id": MODEL_ID,
        "feature_version": FEATURE_VERSION,
        "state_version": STATE_VERSION,
        "probability_version": PROBABILITY_VERSION,
        "input_manifest_hash": manifest_hash,
        "session_date": session.date().isoformat(),
        "decision_as_of": decision_as_of(session).isoformat(),
        "data_status": data_status,
        "market_story": {
            "headline": headline,
            "phase": phase,
            "candidate_phase": _json_value(row.get("candidate_phase")),
            "candidate_streak": _int_or_zero(row.get("candidate_streak")),
            "pressure_level": str(row.get("pressure_level", "UNKNOWN")),
            "direction": str(row.get("direction", "UNKNOWN")),
            "baseline_score": (
                _json_value(row.get("baseline_score")) if data_status == "OK" else None
            ),
            "answers": {
                "carry": str(row.get("carry_answer", "UNKNOWN")),
                "shock": str(row.get("shock_answer", "UNKNOWN")),
                "tail": str(row.get("tail_answer", "UNKNOWN")),
                "persistence": str(row.get("persistence_answer", "UNKNOWN")),
                "repair": str(row.get("repair_answer", "UNKNOWN")),
                "outlook": outlook,
            },
            "scores": {
                "carry_risk": (
                    None if data_status == "UNKNOWN" else _json_value(row.get("carry_risk_score"))
                ),
                "shock": (
                    None if data_status == "UNKNOWN" else _json_value(row.get("shock_score"))
                ),
                "tail_price": (
                    None if data_status == "UNKNOWN" else _json_value(row.get("tail_price_score"))
                ),
                "persistence": (
                    None if data_status == "UNKNOWN" else _json_value(row.get("persistence_score"))
                ),
                "repair": (
                    None if data_status == "UNKNOWN" else _json_value(row.get("repair_score"))
                ),
            },
            "drivers": drivers,
            "counter_evidence": counters,
            "repair_evidence": repair_evidence,
            "structural_triggers": structural_triggers(row) if data_status == "OK" else [],
            "what_changes_the_view": what_changes_the_view(phase),
            "narrative": narrative,
        },
        "probability_judgment": _json_value(probability_judgment),
        "observations": _mapping(row, CORE_OBSERVATION_FIELDS),
        "diagnostics": {
            **(
                {
                    field: (
                        _json_value(row.get(field))
                        if field
                        in {
                            "feature_vintage_kind",
                            "feature_methodology_signature",
                            "pit_evidence",
                            "formal_vintage_eligible",
                        }
                        else None
                    )
                    for field in DIAGNOSTIC_FIELDS
                    if field in row.index
                }
                if data_status == "UNKNOWN"
                else _mapping(row, DIAGNOSTIC_FIELDS)
            ),
            "feature_digest": feature_digest(row),
            "source_rows": _int_or_zero(row.get("source_rows")),
            # Freeze the complete, untruncated five-axis decomposition in the
            # accepted snapshot.  Human-facing evidence must never depend on a
            # later mutable state-history file.
            "component_contributions": (
                component_contributions(row) if data_status == "OK" else []
            ),
        },
        "issues": list(issues or []),
    }
    return cast(dict[str, Any], _json_value(payload))


def load_schema(path: str | Path | None = None) -> dict[str, Any]:
    schema_path = Path(path) if path else project_root() / "schemas" / "daily_output.schema.json"
    return cast(dict[str, Any], json.loads(schema_path.read_text(encoding="utf-8")))


def validate_daily_output(payload: dict[str, Any], schema_path: str | Path | None = None) -> None:
    validator = jsonschema.Draft202012Validator(
        load_schema(schema_path), format_checker=jsonschema.FormatChecker()
    )
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        formatted = "; ".join(
            f"{'/'.join(map(str, error.path)) or '<root>'}: {error.message}" for error in errors
        )
        raise ValueError(f"Daily output schema validation failed: {formatted}")
    # JSON Schema can constrain types and state combinations, but it cannot
    # express cross-field arithmetic.  Enforce the probability truth contract
    # here so a consumer never receives internally inconsistent numbers.
    probability = payload.get("probability_judgment", {})
    for event_id, event in probability.items():
        status = event.get("model_status")
        if status not in {"CALIBRATED_MODEL", "BASE_RATE_ONLY"}:
            continue
        actual = float(event["probability"])
        base = float(event["base_rate"])
        uplift = float(event["uplift"])
        if status == "BASE_RATE_ONLY" and not math.isclose(
            actual, base, rel_tol=0.0, abs_tol=1e-12
        ):
            raise ValueError(
                f"Probability contract failed for {event_id}: "
                "BASE_RATE_ONLY requires probability == base_rate"
            )
        if not math.isclose(actual - base, uplift, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(
                f"Probability contract failed for {event_id}: "
                "uplift must equal probability - base_rate"
            )
