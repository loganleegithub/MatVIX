from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from matvix.calendar import decision_as_of
from matvix.features.builder import _log_change, _regime_groups
from matvix.probability.engine import prepare_probability_artifacts
from matvix.probability.walk_forward import build_oof_ledger
from matvix.state.scores import _rolling_percentile_for_methodology

EVENT_ID = "calm_carry_breaks_5d"
PREDICTORS = ("p_neg_front_slope30", "p_d1_log_vvix", "p_d5_log_vvix", "p_neg_spx_5d_log_momentum")
SPEC_ID = "MATVIX_V3_UNQUALIFIED_FRAGILITY_VETO_SHADOW_1.0.0"
SPEC_SHA256 = "891ff32abe61235f7297684ae7bc4576f470312950782773761aa25da4ca8aa8"
CANDIDATE_OOF_SHA256 = "44e7e43efb207b8b8b56ee20a9c0ab18229046ac2e73eb6dd7d05b4c1c770770"

ADAPTER_SPEC: dict[str, Any] = json.loads(
    '{"adapter_spec_id":"MATVIX_V3_UNQUALIFIED_FRAGILITY_VETO_SHADOW_1.0.0","adapter":{"allowed_position_change":"SVXY_TO_SGOV_ONLY","base_short_allowed":"data_status == OK AND carry == SUPPORTIVE AND shock == CALM AND persistence == NORMAL","common_start":"first common signal session on or after 2023-06-16","long_mapping":"UNCHANGED_V2","missing_score_when_base_short_allowed":"SGOV","short_allowed_v3":"base_short_allowed AND shadow_score_available AND NOT veto","veto":"base_short_allowed AND shadow_score_available AND shadow_score > causal_base_rate"},"candidate":{"event_id":"calm_carry_breaks_5d","eligibility":["data_status == OK","formal_vintage_eligible == true","carry_answer == SUPPORTIVE","shock_answer == CALM","persistence_answer == NORMAL","all predictors observable at t"],"horizon_sessions":5,"positive_components":["hard_acute == true","front_slope30 < 0","broad_pressure_day == true","carry_environment_state == CLOSED for two consecutive future sessions"],"outcome_availability":"after all four facts for the fifth future formal session are known","predictors":["p_neg_front_slope30","p_d1_log_vvix","p_d5_log_vvix","p_neg_spx_5d_log_momentum"],"percentile":{"reference_sessions":756,"minimum_valid":504,"exclude_current":true,"methodology_isolation":true},"base_rate":{"max_samples":756,"minimum_samples":252,"alpha":1.0,"beta":1.0},"logistic":{"implementation":"scikit-learn==1.7.2","C":1.0,"solver":"lbfgs","fit_intercept":true,"tol":1e-08,"max_iter":1500,"random_state":0,"max_training_samples":1500,"min_training_samples":252,"min_positive":30,"min_negative":30,"purge_sessions":20},"rolling_intercept":{"max_samples":252,"min_positive":20,"min_negative":20,"slope":1.0,"root_lower":-40.0,"root_upper":40.0,"clip_min":1e-06,"clip_max":0.999999},"score_source":"candidate OOF published_probability before the 252-row formal model gate"}}'
)


def adapter_spec_sha256() -> str:
    return hashlib.sha256(json.dumps(ADAPTER_SPEC, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def add_shadow_predictors(states: pd.DataFrame) -> pd.DataFrame:
    frame = states.sort_values("session_date", kind="stable").reset_index(drop=True).copy()
    if frame["session_date"].duplicated().any():
        raise ValueError("Fragility shadow requires one state row per session")
    for output, source, periods, sign in (
        ("p_d1_log_vvix", "vvix_close", 1, 1.0),
        ("p_neg_spx_5d_log_momentum", "spx_close", 5, -1.0),
    ):
        raw = pd.Series(np.nan, index=frame.index, dtype=float)
        for indices in _regime_groups(frame["feature_methodology_signature"]):
            raw.loc[indices] = sign * _log_change(frame.loc[indices, source], periods)
        frame[output] = _rolling_percentile_for_methodology(
            raw, frame["feature_methodology_signature"], reference_sessions=756, minimum_valid=504)
    return frame


def build_shadow_target_ledger(states: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for index, row in states.iterrows():
        observable = bool(row.get("data_status") == "OK"
                          and bool(row.get("formal_vintage_eligible", False))
                          and all(pd.notna(row.get(name)) for name in PREDICTORS))
        eligible = bool(observable and row.get("carry_answer") == "SUPPORTIVE"
                        and row.get("shock_answer") == "CALM"
                        and row.get("persistence_answer") == "NORMAL")
        status = "ELIGIBLE" if eligible else "NOT_APPLICABLE" if observable else "UNOBSERVABLE"
        record: dict[str, object] = {
            "event_id": EVENT_ID, "prediction_date": pd.Timestamp(row["session_date"]).normalize(),
            "event_status": status, "label": np.nan,
            "label_status": "NOT_APPLICABLE" if status == "NOT_APPLICABLE" else "CENSORED",
            "horizon_sessions": 5, "valid_through_session": pd.NaT,
            "outcome_available_at": pd.NaT,
            "formal_vintage_eligible": bool(row.get("formal_vintage_eligible", False)),
        }
        if eligible and index + 5 < len(states):
            future = states.iloc[index + 1 : index + 6]
            facts = (("hard_acute", "hard_acute_formal_vintage_eligible"), ("front_slope30", "front_curve_formal_vintage_eligible"), ("broad_pressure_day", "broad_pressure_day_formal_vintage_eligible"), ("carry_environment_state", "carry_environment_formal_vintage_eligible"))
            complete = all(
                future[value].notna().all() and future[flag].eq(True).all()
                for value, flag in facts
            ) and future["carry_environment_state"].ne("UNKNOWN").all()
            if complete:
                carry = future["carry_environment_state"].tolist()
                positive = bool(
                    future["hard_acute"].any()
                    or future["front_slope30"].lt(0).any()
                    or future["broad_pressure_day"].any()
                    or any(a == b == "CLOSED" for a, b in zip(carry, carry[1:], strict=False))
                )
                final = pd.Timestamp(future.iloc[-1]["session_date"]).normalize()
                record.update({"label": int(positive),
                               "label_status": "OBSERVED_1" if positive else "OBSERVED_0",
                               "valid_through_session": final,
                               "outcome_available_at": pd.Timestamp(decision_as_of(final))})
        records.append(record)
    return pd.DataFrame(records)


def build_shadow_oof(states: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    frame = add_shadow_predictors(states)
    targets = build_shadow_target_ledger(frame)
    return frame, targets, build_oof_ledger(frame, targets, EVENT_ID, feature_names=PREDICTORS)


def _parquet_sha256(frame: pd.DataFrame) -> str:
    with tempfile.NamedTemporaryFile(suffix=".parquet") as output:
        frame.to_parquet(output.name, engine="pyarrow", index=False)
        return hashlib.sha256(Path(output.name).read_bytes()).hexdigest()


def verify_frozen_replay(states: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame, targets, oof = build_shadow_oof(states)
    formal_targets, formal_oof = prepare_probability_artifacts(frame)
    completed = oof["label_status"].isin(("OBSERVED_0", "OBSERVED_1"))
    combined_targets = pd.concat([formal_targets, targets], ignore_index=True).sort_values(
        ["event_id", "prediction_date"], kind="stable"
    ).reset_index(drop=True)
    evidence = {
        "eligible_targets": int(targets["event_status"].eq("ELIGIBLE").sum()),
        "completed_targets": int(targets["label_status"].isin(("OBSERVED_0", "OBSERVED_1")).sum()),
        "target_positive": int(targets["label"].sum()), "published_oof": int(len(oof)),
        "completed_published_oof": int(completed.sum()),
        "completed_oof_positive": int(oof.loc[completed, "label"].sum()),
        "first_score_session": pd.Timestamp(oof["prediction_date"].min()).date().isoformat(),
        "formal_oof_sha256": _parquet_sha256(formal_oof),
        "candidate_target_sha256": _parquet_sha256(combined_targets),
        "candidate_oof_sha256": _parquet_sha256(pd.concat([formal_oof, oof], ignore_index=True)),
    }
    expected = {
        "eligible_targets": 372, "completed_targets": 371, "target_positive": 158,
        "published_oof": 115, "completed_published_oof": 114,
        "completed_oof_positive": 44, "first_score_session": "2023-06-16",
        "formal_oof_sha256": "330476772918f52d1d588577ea337bd7b6ed596a3049294716e3c14dfa34f820", "candidate_target_sha256": "9e77c5be6e2f4a2b387d877b7f5184376f922301a2585077f0704382a920523e", "candidate_oof_sha256": CANDIDATE_OOF_SHA256,
    }
    if evidence != expected:
        raise ValueError(f"Frozen fragility replay mismatch: {evidence}")
    return oof, evidence


def build_v3_adapter(states: pd.DataFrame, shadow_oof: pd.DataFrame) -> pd.DataFrame:
    mapping = {"carry_answer": "carry", "shock_answer": "shock", "persistence_answer": "persistence"}
    weather = states[["session_date", "data_status", *mapping]].rename(columns=mapping).copy()
    weather["session_date"] = pd.to_datetime(weather["session_date"]).dt.normalize()
    scores = shadow_oof[["prediction_date", "published_probability", "base_rate_at_prediction", "calibration_method"]].rename(columns={"prediction_date": "session_date", "published_probability": "shadow_score", "base_rate_at_prediction": "causal_base_rate", "calibration_method": "shadow_transform"})
    weather = weather.merge(scores, on="session_date", how="left", validate="one_to_one")
    weather["weather_version"] = "V3"
    weather["decision_as_of"] = weather["session_date"].map(decision_as_of)
    weather["shadow_score_kind"] = "UNQUALIFIED_RESEARCH_SCORE"
    weather["qualification_status"] = "INSUFFICIENT_PUBLISHED_OOF"
    weather["formal_event_id"] = None
    weather["formal_model_status"] = None
    weather["base_short_allowed"] = (
        weather["data_status"].eq("OK") & weather["carry"].eq("SUPPORTIVE")
        & weather["shock"].eq("CALM") & weather["persistence"].eq("NORMAL")
    )
    weather["shadow_score"] = pd.to_numeric(weather["shadow_score"], errors="coerce")
    weather["causal_base_rate"] = pd.to_numeric(weather["causal_base_rate"], errors="coerce")
    weather["shadow_score_available"] = np.isfinite(weather["shadow_score"]) & np.isfinite(weather["causal_base_rate"])
    weather["unqualified_fragility_veto_shadow"] = (
        weather["base_short_allowed"] & weather["shadow_score_available"]
        & weather["shadow_score"].gt(weather["causal_base_rate"])
    )
    weather["short_allowed_v3"] = (
        weather["base_short_allowed"] & weather["shadow_score_available"]
        & ~weather["unqualified_fragility_veto_shadow"]
    )
    return weather.sort_values("session_date").reset_index(drop=True)


if adapter_spec_sha256() != SPEC_SHA256:
    raise RuntimeError("Frozen fragility adapter spec digest mismatch")
