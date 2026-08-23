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
        "release_ref": "matvix-v3.0.0",
        "package_version": "3.0.0",
        "model_id": MODEL_ID,
        "schema_version": SCHEMA_VERSION,
        "feature_version": FEATURE_VERSION,
        "state_version": STATE_VERSION,
        "probability_version": PROBABILITY_VERSION,
    }
    assert manifest["product_boundary"]["trading_authorized"] is False
    assert manifest["authorized_data_requirement"]["restricted_data_included"] is False
    for relative, expected in manifest["frozen_configuration"]["files"].items():
        assert _sha256(PROJECT_ROOT / relative) == expected
    lock = manifest["runtime"]["requirements_lock"]
    assert _sha256(PROJECT_ROOT / lock["path"]) == lock["sha256"]
    prospective = manifest["scientific_evidence"]["prospective_fragility_ledger"]
    assert _sha256(PROJECT_ROOT / "data/prospective/v3_fragility_shadow_ledger.csv") == prospective[
        "sha256"
    ]
