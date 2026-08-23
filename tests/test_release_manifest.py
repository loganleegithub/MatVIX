from __future__ import annotations

import hashlib
import json
from pathlib import Path

from matvix.constants import (
    FEATURE_VERSION,
    MODEL_ID,
    PROBABILITY_VERSION,
    SCHEMA_VERSION,
    STATE_VERSION,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_release_manifest_binds_the_tracked_v3_surface() -> None:
    manifest = json.loads(
        (PROJECT_ROOT / "MATVIX_V3_RELEASE_MANIFEST.json").read_text(encoding="utf-8")
    )
    release = manifest["release"]
    assert release == {
        "name": "MatVIX V3",
        "release_ref": "matvix-v3.0.1",
        "package_version": "3.0.1",
        "model_id": MODEL_ID,
        "schema_version": SCHEMA_VERSION,
        "feature_version": FEATURE_VERSION,
        "state_version": STATE_VERSION,
        "probability_version": PROBABILITY_VERSION,
    }
    assert manifest["release_closure"] == {
        "status": "RESEARCH_STATION_READY",
        "operating_mode": "READ_ONLY",
        "trading_authority": "NONE",
        "historical_core": "ACCEPTED",
        "prospective_confirmation": "PENDING",
    }
    assert manifest["release_verification"] == {
        "verified_on": "2026-08-23",
        "environment": "ISOLATED_CLEAN_SOURCE_EXPORT_FRESH_VENV",
        "platform": "macOS 26.5.1 arm64",
        "python": "3.12.13",
        "authorized_input_identities": 194,
        "rebuild_status": "PASS",
        "byte_identical_release_artifacts": 10,
        "pytest": {"status": "PASS", "collected": 247},
        "ruff": "PASS",
        "mypy": "PASS",
        "doctor": "PASS",
        "runtime_smoke": {
            "runtime_status": "RUNNING",
            "product_status": "READY",
            "trading_authorized": False,
            "last_good_session": "2026-08-20",
        },
    }
    assert manifest["product_boundary"]["trading_authorized"] is False
    authorized_data = manifest["authorized_data_requirement"]
    assert authorized_data["restricted_data_included"] is False
    live_manifest = PROJECT_ROOT / authorized_data["live_generation_manifest_path"]
    assert _sha256(live_manifest) == authorized_data["live_generation_manifest_sha256"]
    loaded_live_manifest = json.loads(live_manifest.read_text(encoding="utf-8"))
    assert len(loaded_live_manifest["files"]) == authorized_data["live_generation_manifest_entries"]
    for relative, expected in manifest["frozen_configuration"]["files"].items():
        assert _sha256(PROJECT_ROOT / relative) == expected
    lock = manifest["runtime"]["requirements_lock"]
    assert _sha256(PROJECT_ROOT / lock["path"]) == lock["sha256"]
    prospective = manifest["scientific_evidence"]["prospective_fragility_ledger"]
    assert _sha256(PROJECT_ROOT / "data/prospective/v3_fragility_shadow_ledger.csv") == prospective[
        "sha256"
    ]
    assert manifest["scientific_evidence"]["fragility_boundary"] == {
        "event_id": "calm_carry_breaks_5d",
        "formal_model_status": "NOT_ELIGIBLE",
        "formal_model_pass_claimed": False,
        "rejection_reason": "REJECTED_INSUFFICIENT_PUBLISHED_OOF",
        "completed_published_oof": 114,
        "required_published_oof": 252,
        "candidate_artifact_sha256": (
            "44e7e43efb207b8b8b56ee20a9c0ab18229046ac2e73eb6dd7d05b4c1c770770"
        ),
    }
    assert manifest["scientific_evidence"]["stage_d_historical_comparator"] == {
        "classification": "FROZEN_HISTORICAL_COMPARATOR",
        "current_runtime_authority": False,
        "required_authorized_evidence": True,
        "daily": {
            "path": (
                "data/raw/release_evidence/v3_stage_d/historical_comparator_daily.parquet"
            ),
            "sha256": (
                "c87e4c2f4be4c5c5ad2a4a4d251ba9f3bb758a5caa4e0549f3f7baf6e680c01f"
            ),
            "rows": 3334,
        },
        "summary": {
            "path": (
                "data/raw/release_evidence/v3_stage_d/historical_comparator_summary.json"
            ),
            "sha256": (
                "a3d587761ed6f83a4bae17ac55dfe2560c5c3750f86c0597949e387ee1bf66b3"
            ),
        },
    }
