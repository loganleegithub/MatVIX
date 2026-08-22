from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from matvix.config import _validate_project_release, project_root
from matvix.config_contract import ConfigContractError, validate_frozen_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _copy_release_configs(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(PROJECT_ROOT / "configs", root / "configs")
    return root


def _scoring_with_changed_acute_threshold(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["hard_acute"] = (result["shock_score"] >= 86.0) & (
        result["front_confirmation_count"] >= 2
    )
    result["direction"] = "STABLE"
    result.loc[result["d5_baseline_score"] >= 7.5, "direction"] = "RISING"
    result.loc[result["d5_baseline_score"] <= -7.5, "direction"] = "FALLING"
    return result


def _acceptance_with_changed_skill(frame: pd.DataFrame) -> dict[str, object]:
    if len(frame) < 252:
        return {"accepted": False, "samples": len(frame)}
    positives = int(frame["label"].sum())
    negatives = len(frame) - positives
    if positives < 20 or negatives < 20:
        return {"accepted": False, "samples": len(frame)}
    skill = 0.10
    ece = 0.01
    return {
        "accepted": bool(skill >= 0.03 and ece <= 0.07),
        "samples": 252,
    }


def test_checked_in_release_config_is_bound_to_runtime_semantics() -> None:
    report = validate_frozen_config(PROJECT_ROOT)

    assert report.versions == {
        "source_manifest.yaml": "1.0.0",
        "features_v2.yaml": "2.0.0",
        "state_v2.yaml": "2.0.0",
        "probability_v2.yaml": "2.0.0",
    }
    assert report.config_bundle_digest.startswith("sha256:")


def test_yaml_comment_and_format_changes_do_not_change_contract(tmp_path: Path) -> None:
    root = _copy_release_configs(tmp_path)
    feature_path = root / "configs" / "features_v2.yaml"
    feature_path.write_text(
        feature_path.read_text(encoding="utf-8") + "\n# release operator note\n",
        encoding="utf-8",
    )

    validate_frozen_config(root)


def test_config_value_change_without_versioned_release_is_rejected(tmp_path: Path) -> None:
    root = _copy_release_configs(tmp_path)
    probability_path = root / "configs" / "probability_v2.yaml"
    probability_path.write_text(
        probability_path.read_text(encoding="utf-8").replace(
            "min_training_samples: 252", "min_training_samples: 253"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigContractError, match="probability_v2.yaml: semantic digest"):
        validate_frozen_config(root)


def test_source_manifest_structure_change_is_rejected(tmp_path: Path) -> None:
    root = _copy_release_configs(tmp_path)
    manifest_path = root / "configs" / "source_manifest.yaml"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8") + "\nunreviewed_field: true\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigContractError, match="source_manifest.yaml: semantic digest"):
        validate_frozen_config(root)


def test_state_threshold_code_change_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    import matvix.state.scores as scores

    monkeypatch.setattr(scores, "add_percentiles_and_scores", _scoring_with_changed_acute_threshold)

    with pytest.raises(ConfigContractError, match="state.thresholds"):
        validate_frozen_config(PROJECT_ROOT)


def test_probability_acceptance_threshold_code_change_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import matvix.probability.calibration as calibration

    monkeypatch.setattr(calibration, "acceptance_metrics", _acceptance_with_changed_skill)

    with pytest.raises(ConfigContractError, match="probability.acceptance"):
        validate_frozen_config(PROJECT_ROOT)


def test_project_root_runs_release_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _copy_release_configs(tmp_path)
    feature_path = root / "configs" / "features_v2.yaml"
    feature_path.write_text(
        feature_path.read_text(encoding="utf-8").replace('version: "2.0.0"', 'version: "9.0.0"', 1),
        encoding="utf-8",
    )
    monkeypatch.setenv("MATVIX_PROJECT_DIR", str(root))
    _validate_project_release.cache_clear()

    with pytest.raises(ConfigContractError, match="explicit versioned release"):
        project_root()

    _validate_project_release.cache_clear()
