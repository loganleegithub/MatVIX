from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from matvix.calendar import decision_as_of
from matvix.constants import EVENT_ORDER
from matvix.data.assemble import daily_vintage_summary, observations_to_wide
from matvix.data.point_in_time import filter_as_of, select_historical_point_in_time
from matvix.features.builder import build_feature_table
from matvix.features.futures_curve import select_standard_monthly_curve
from matvix.output import build_daily_output, input_manifest_hash, validate_daily_output
from matvix.probability.engine import (
    outlook_answer,
    resolve_probability_artifacts,
    run_probability_job,
)
from matvix.probability.targets import add_event_statuses
from matvix.probability.walk_forward import ProbabilitySpec
from matvix.source_identity import (
    admit_official_observations,
    admit_official_vx_settlements,
)
from matvix.state.scores import add_percentiles_and_scores
from matvix.state.transitions import build_state_table
from matvix.storage import read_json, read_parquet, write_json, write_parquet


@dataclass(frozen=True)
class ProjectPaths:
    root: Path

    @property
    def observations(self) -> Path:
        return self.root / "data" / "raw" / "observations.parquet"

    @property
    def vx_contracts(self) -> Path:
        return self.root / "data" / "raw" / "vx_contracts.parquet"

    @property
    def features(self) -> Path:
        return self.root / "data" / "processed" / "features.parquet"

    @property
    def states(self) -> Path:
        return self.root / "data" / "processed" / "states.parquet"

    @property
    def targets(self) -> Path:
        return self.root / "data" / "probability" / "target_ledger.parquet"

    @property
    def oof(self) -> Path:
        return self.root / "data" / "probability" / "oof_ledger.parquet"

    @property
    def probability_metadata(self) -> Path:
        return self.root / "data" / "probability" / "latest_metadata.json"

    @property
    def probability_artifact_contract(self) -> Path:
        return self.root / "data" / "probability" / "artifact_contract.json"

    @property
    def daily_output_dir(self) -> Path:
        return self.root / "outputs" / "daily"


def build_state_history(
    observations: pd.DataFrame,
    vx_contracts: pd.DataFrame,
    *,
    reference_sessions: int = 756,
    minimum_valid: int = 504,
    formal_chain: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    observation_candidates = (
        admit_official_observations(observations) if formal_chain else observations
    )
    vx_candidates = admit_official_vx_settlements(vx_contracts) if formal_chain else vx_contracts
    admitted_observations = select_historical_point_in_time(
        observation_candidates, entity_columns=["series_id"], formal_only=formal_chain
    )
    admitted_vx = select_historical_point_in_time(
        vx_candidates, entity_columns=["contract_id"], formal_only=formal_chain
    )
    wide = observations_to_wide(admitted_observations)
    vintages = daily_vintage_summary(admitted_observations)
    core_columns = [
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
    ]
    complete_raw = wide.loc[wide[core_columns].notna().all(axis=1), "session_date"]
    valid_vx = admitted_vx.loc[
        pd.to_numeric(admitted_vx.get("settle"), errors="coerce").gt(0),
        "session_date",
    ]
    if not complete_raw.empty and not valid_vx.empty:
        # Before both foundations exist no axis, state or probability can be
        # formed.  Starting at the later first date preserves every usable
        # observation while avoiding decades of guaranteed UNKNOWN rows.
        usable_start = max(
            pd.Timestamp(complete_raw.min()).normalize(),
            pd.Timestamp(valid_vx.min()).normalize(),
        )
        wide = wide.loc[
            pd.to_datetime(wide["session_date"]).dt.normalize() >= usable_start
        ].reset_index(drop=True)
        vintages = vintages.loc[
            pd.to_datetime(vintages["session_date"]).dt.normalize() >= usable_start
        ].reset_index(drop=True)
    features = build_feature_table(wide, admitted_vx, vintages)
    # This boundary records whether all feature inputs came through the formal
    # PIT selector.  Downstream event-predicate lineage can then be specific to
    # the fields it actually uses, instead of inheriting an unrelated row-wide
    # data gap.
    features["formal_chain_admitted"] = bool(formal_chain)
    scored = add_percentiles_and_scores(
        features,
        reference_sessions=reference_sessions,
        minimum_valid=minimum_valid,
    )
    states = build_state_table(scored)
    # The persisted feature table includes raw features, rolling percentiles, and fixed-weight scores.
    return scored, states


def _unobservable_events() -> dict[str, dict[str, Any]]:
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


def _manifest_for_session(
    observations: pd.DataFrame,
    vx_contracts: pd.DataFrame,
    session_date: pd.Timestamp,
) -> pd.DataFrame:
    session = pd.Timestamp(session_date).normalize()
    spot = admit_official_observations(observations)
    spot["session_date"] = pd.to_datetime(spot["session_date"]).dt.normalize()
    spot = spot.loc[spot["session_date"] == session]
    if not spot.empty:
        spot = filter_as_of(spot, decision_as_of(session))
    admitted_vx = select_historical_point_in_time(
        admit_official_vx_settlements(vx_contracts),
        entity_columns=["contract_id"],
        formal_only=True,
    )
    curve = select_standard_monthly_curve(admitted_vx, session, count=7)
    fields = ["series_id", "session_date", "revision_id"]
    pieces: list[pd.DataFrame] = []
    if not spot.empty:
        pieces.append(spot[fields])
    if not curve.empty:
        vx = curve.copy()
        vx["series_id"] = vx["contract_id"].map(lambda value: f"VX_SETTLE:{value}")
        pieces.append(vx[fields])
    if not pieces:
        return pd.DataFrame(
            [{"series_id": "MISSING", "session_date": session, "revision_id": "missing"}]
        )
    return pd.concat(pieces, ignore_index=True)


def build_snapshot_payload(
    states: pd.DataFrame,
    observations: pd.DataFrame,
    vx_contracts: pd.DataFrame,
    *,
    session_date: pd.Timestamp | str,
    formal_runtime_required: bool = True,
    target_ledger: pd.DataFrame | None = None,
    oof_ledger: pd.DataFrame | None = None,
) -> tuple[dict[str, Any], dict[str, Any], pd.DataFrame, pd.DataFrame]:
    session = pd.Timestamp(session_date).normalize()
    matching = states.loc[pd.to_datetime(states["session_date"]).dt.normalize() == session]
    if matching.empty:
        raise KeyError(f"No state row for {session.date()}")
    state_row = matching.iloc[-1].copy()
    issues: list[str] = []
    if str(state_row.get("data_status")) == "OK":
        try:
            events, metadata, targets, oof = run_probability_job(
                states,
                prediction_date=session,
                formal_runtime_required=formal_runtime_required,
                target_ledger=target_ledger,
                oof_ledger=oof_ledger,
            )
        except Exception as exc:  # preserve the daily state even when the optional job fails
            status_row = (
                add_event_statuses(states)
                .loc[pd.to_datetime(states["session_date"]).dt.normalize() == session]
                .iloc[-1]
            )
            events = {}
            for event in EVENT_ORDER:
                status = str(status_row[f"{event}__event_status"])
                if status == "ELIGIBLE":
                    events[event] = {
                        "event_status": "ELIGIBLE",
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
                        "interpretation": "概率作业尚未成功完成",
                    }
                elif status == "NOT_APPLICABLE":
                    events[event] = {
                        "event_status": "NOT_APPLICABLE",
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
                        "interpretation": "当前状态已存在或该转移问题不适用",
                    }
                else:
                    events[event] = _unobservable_events()[event]
            metadata, targets, oof = (
                {"job_error": f"{type(exc).__name__}: {exc}"},
                pd.DataFrame(),
                pd.DataFrame(),
            )
            issues.append("PROBABILITY_JOB_FAILED")
    else:
        events, metadata, targets, oof = _unobservable_events(), {}, pd.DataFrame(), pd.DataFrame()
    state_row["outlook_answer"] = outlook_answer(str(state_row.get("data_status")), events)
    manifest = _manifest_for_session(observations, vx_contracts, session)
    missing_core = []
    for field in (
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
    ):
        value = state_row.get(field)
        if value is None or pd.isna(value):
            missing_core.append(field)
    if missing_core:
        issues.append("MISSING_CORE_INPUTS:" + ",".join(missing_core))
    curve_ids = state_row.get("vx_contract_ids")
    # Arrow restores list columns as NumPy arrays.  The persisted and
    # in-memory representations are the same canonical F1-F7 curve.
    curve_count = len(curve_ids) if isinstance(curve_ids, (list, tuple, np.ndarray)) else 0
    if curve_count != 7:
        issues.append(f"INCOMPLETE_VX_F1_F7:{curve_count}/7")

    negative_forward_variance = [
        field
        for field in ("fvar_9_30", "fvar_30_93", "fvar_93_184")
        if field in state_row.index
        and pd.notna(state_row.get(field))
        and float(state_row.get(field)) < 0.0
    ]
    issues.extend(f"NEGATIVE_FORWARD_VARIANCE:{field}" for field in negative_forward_variance)
    if state_row.get("data_status") != "OK":
        issues.append("CORE_SNAPSHOT_INCOMPLETE_OR_NON_FORMAL")
    payload = build_daily_output(
        state_row,
        events,
        manifest_hash=input_manifest_hash(manifest),
        issues=issues,
    )
    validate_daily_output(payload)
    return payload, metadata, targets, oof


def persist_history(
    paths: ProjectPaths,
    observations: pd.DataFrame,
    vx_contracts: pd.DataFrame,
    features: pd.DataFrame,
    states: pd.DataFrame,
) -> None:
    write_parquet(observations, paths.observations)
    write_parquet(vx_contracts, paths.vx_contracts)
    write_parquet(features, paths.features)
    write_parquet(states, paths.states)


def persist_snapshot(
    paths: ProjectPaths,
    payload: dict[str, Any],
    metadata: dict[str, Any],
    targets: pd.DataFrame,
    oof: pd.DataFrame,
) -> Path:
    session = str(payload["session_date"])
    # Publish the consumer-facing daily JSON last.  A failed ledger/metadata
    # write can therefore never expose a new snapshot beside stale supporting
    # artifacts.
    if not targets.empty:
        write_parquet(targets, paths.targets)
    if not oof.empty:
        write_parquet(oof, paths.oof)
    write_json(metadata, paths.probability_metadata)
    target = write_json(payload, paths.daily_output_dir / f"{session}.json")
    return target


def persist_probability_artifacts(
    paths: ProjectPaths,
    targets: pd.DataFrame,
    oof: pd.DataFrame,
    contract: dict[str, Any],
) -> None:
    """Publish ledgers first and their validating contract last.

    If the process stops between writes, the prior contract digest cannot match
    the partial files, so the next run performs a full rebuild instead of
    accepting a mixed cache generation.
    """

    write_parquet(targets, paths.targets)
    write_parquet(oof, paths.oof)
    write_json(contract, paths.probability_artifact_contract)


def resolve_persisted_probability_artifacts(
    paths: ProjectPaths,
    states: pd.DataFrame,
    *,
    spec: ProbabilitySpec | None = None,
    formal_runtime_required: bool = True,
    force_full_rebuild: bool = False,
    persist: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], str]:
    """Load only digest-validated artifacts, otherwise rebuild or append."""

    cache_complete = all(
        path.exists() for path in (paths.targets, paths.oof, paths.probability_artifact_contract)
    )
    if cache_complete:
        cached_targets = read_parquet(paths.targets)
        cached_oof = read_parquet(paths.oof)
        cached_contract = read_json(paths.probability_artifact_contract)
    else:
        cached_targets = None
        cached_oof = None
        cached_contract = None

    targets, oof, contract, action = resolve_probability_artifacts(
        states,
        cached_targets=cached_targets,
        cached_oof=cached_oof,
        cached_contract=cached_contract,
        spec=spec,
        formal_runtime_required=formal_runtime_required,
        force_full_rebuild=force_full_rebuild,
    )
    if persist and action != "EXACT_CACHE_HIT":
        persist_probability_artifacts(paths, targets, oof, contract)
    return targets, oof, contract, action


def load_persisted_inputs(paths: ProjectPaths) -> tuple[pd.DataFrame, pd.DataFrame]:
    return read_parquet(paths.observations), read_parquet(paths.vx_contracts)


def load_persisted_states(paths: ProjectPaths) -> pd.DataFrame:
    return read_parquet(paths.states)
