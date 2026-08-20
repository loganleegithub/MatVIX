from __future__ import annotations

import ast
import hashlib
import inspect
import json
import textwrap
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigContractError(RuntimeError):
    """A release manifest and its executable parameters disagree."""


@dataclass(frozen=True)
class ConfigContractReport:
    versions: dict[str, str]
    config_bundle_digest: str


# Parsed YAML is frozen; comments and formatting are intentionally not.
_FROZEN = {
    "source_manifest.yaml": (
        "manifest_version",
        "1.0.0",
        "390b01396d26f09d77b1393fd890d625a951df9c15eecca45e04497c0098d168",
    ),
    "features_v1.yaml": (
        "version",
        "1.0.0",
        "2d2eaed70327573a1f6e17b4cf2e2e6276843b1483af0805f702c87658fc9e72",
    ),
    "state_v1.yaml": (
        "version",
        "1.0.0",
        "323157700580106d051553d16ea4e31c32255c958f42eccd2bee3b08aa91aa95",
    ),
    "probability_v1.yaml": (
        "version",
        "1.1.0",
        "673d4bfad11d6ce6ee7905277de3ffb469ab5c1323966f617fa83282f569ec44",
    ),
}


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _tree(function: Callable[..., Any]) -> ast.Module:
    return ast.parse(textwrap.dedent(inspect.getsource(function)))


def _number(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_number(node.operand)
    raise ValueError("not numeric")


def _field(node: ast.AST) -> str | None:
    if isinstance(node, (ast.Name, ast.Attribute)):
        return node.id if isinstance(node, ast.Name) else node.attr
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        return node.slice.value if isinstance(node.slice.value, str) else None
    if isinstance(node, ast.Call) and node.args:
        return _field(node.args[0])
    return None


def _facts(function: Callable[..., Any]) -> Counter[tuple[str, str, float]]:
    """Extract named numeric comparisons only; unrelated code is ignored."""
    result: Counter[tuple[str, str, float]] = Counter()
    for node in ast.walk(_tree(function)):
        if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
            try:
                field, value = _field(node.left), _number(node.comparators[0])
            except ValueError:
                continue
            if field:
                result[(field, type(node.ops[0]).__name__, value)] += 1
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_compare"
        ):
            try:
                field = _field(node.args[0])
                operator_node = node.args[1]
                if not isinstance(operator_node, ast.Constant):
                    continue
                operator = operator_node.value
                value = _number(node.args[2])
            except (AttributeError, IndexError, ValueError):
                continue
            if field and isinstance(operator, str):
                result[(field, operator, value)] += 1
    return result


def _default(function: Callable[..., Any], name: str) -> Any:
    return inspect.signature(function).parameters[name].default


def _same(errors: list[str], label: str, runtime: Any, configured: Any) -> None:
    if runtime != configured:
        errors.append(f"{label}: runtime={runtime!r}, config={configured!r}")


def _feature_contract(config: dict[str, Any], errors: list[str]) -> None:
    from matvix.constants import FEATURE_VERSION, MODEL_ID
    from matvix.features.futures_curve import select_standard_monthly_curve
    from matvix.features.percentile import rolling_midrank_percentile
    from matvix.features.vrp import ewma94_variance

    _same(errors, "features.version", FEATURE_VERSION, config["version"])
    _same(errors, "features.model_id", MODEL_ID, config["model_id"])
    pct = config["percentile"]
    _same(
        errors,
        "features.percentile.reference_sessions",
        _default(rolling_midrank_percentile, "reference_sessions"),
        pct["reference_sessions"],
    )
    _same(
        errors,
        "features.percentile.minimum_valid",
        _default(rolling_midrank_percentile, "minimum_valid"),
        pct["minimum_valid"],
    )
    _same(
        errors,
        "features.percentile.exclude_current",
        "values[start:index]" in inspect.getsource(rolling_midrank_percentile),
        pct["exclude_current"],
    )
    _same(
        errors,
        "features.futures.curve_contracts",
        _default(select_standard_monthly_curve, "count"),
        config["futures"]["curve_contracts"],
    )
    vrp = config["vrp"]
    _same(errors, "features.vrp.lambda", _default(ewma94_variance, "lambda_"), vrp["lambda"])
    _same(
        errors,
        "features.vrp.seed_returns",
        _default(ewma94_variance, "seed_returns"),
        vrp["seed_returns"],
    )


_WEIGHT_KEYS = {
    "carry_risk": ("front_slope30", "basis30_eod", "d5_front_slope30"),
    "shock": ("near_stress", "d1_log_vix", "d5_log_vix", "d5_log_vvix", "vvix"),
    "tail_price": ("skew", "d5_skew"),
    "persistence": (
        "fvol_30_93",
        "fvol_93_184",
        "d5_fvol_30_93",
        "curve_inversion_share",
    ),
    "repair": (
        "d5_log_vix",
        "d5_near_stress",
        "d5_front_slope30",
        "d5_log_vvix",
        "d5_fvol_30_93",
    ),
}


def _state_contract(config: dict[str, Any], errors: list[str]) -> None:
    from matvix.constants import STATE_VERSION
    from matvix.state.ontology import add_state_predicates_and_answers
    from matvix.state.scores import (
        AXIS_BASELINE_WEIGHTS,
        AXIS_COMPONENTS,
        add_percentiles_and_scores,
    )

    _same(errors, "state.version", STATE_VERSION, config["version"])
    for axis, keys in _WEIGHT_KEYS.items():
        runtime = dict(zip(keys, (item[2] for item in AXIS_COMPONENTS[axis]), strict=True))
        _same(errors, f"state.weights.{axis}", runtime, config["weights"][axis])
    _same(
        errors,
        "state.baseline_weights",
        dict(AXIS_BASELINE_WEIGHTS),
        config["baseline_weights"],
    )
    t = config["thresholds"]
    score, ontology = _facts(add_percentiles_and_scores), _facts(add_state_predicates_and_answers)
    expected = [
        (score, ("shock_score", "GtE", float(t["hard_acute_score"])), 1),
        (score, ("front_confirmation_count", "GtE", float(t["hard_acute_confirmations"])), 1),
        (score, ("d5_baseline_score", "GtE", float(t["direction_change"])), 1),
        (score, ("d5_baseline_score", "LtE", -float(t["direction_change"])), 1),
        (ontology, ("persistence_score", ">=", float(t["persistent_score"])), 1),
        (ontology, ("baseline_score", ">=", float(t["persistent_baseline"])), 1),
        (ontology, ("baseline_score", ">=", float(t["stress_baseline"])), 1),
        (ontology, ("repair_score", ">=", float(t["repair_confirmed"])), 2),
        (ontology, ("repair_score", ">=", float(t["repair_building"])), 1),
    ]
    if any(facts[fact] != count for facts, fact, count in expected):
        errors.append("state.thresholds: executable comparisons differ from config")
    source = inspect.getsource(add_state_predicates_and_answers)
    windows = (
        f"at_least_k_true(p_window, {t['persistent_required']})",
        f"index - {t['persistent_window'] - 1}",
        f"index - {t['recent_stress_window'] - 1}",
    )
    if any(fragment not in source for fragment in windows):
        errors.append("state.thresholds: window semantics differ from config")


def _probability_contract(config: dict[str, Any], errors: list[str]) -> None:
    from matvix.constants import EVENT_ORDER, PROBABILITY_VERSION
    from matvix.probability.baseline import beta_smoothed_base_rate
    from matvix.probability.calibration import acceptance_metrics, apply_platt, fit_platt
    from matvix.probability.walk_forward import (
        ProbabilitySpec,
        make_logistic,
        runtime_contract_status,
    )

    _same(errors, "probability.version", PROBABILITY_VERSION, config["version"])
    _same(errors, "probability.event_order", list(EVENT_ORDER), config["event_order"])
    spec = asdict(ProbabilitySpec())
    base, logistic, platt = config["base_rate"], config["logistic"], config["platt"]
    spec_bindings = {
        "base_rate_max": base["max_samples"],
        "base_rate_min": base["minimum_samples"],
        "training_max": logistic["max_training_samples"],
        "training_min": logistic["min_training_samples"],
        "training_min_positive": logistic["min_positive"],
        "training_min_negative": logistic["min_negative"],
        "purge_sessions": logistic["purge_sessions"],
        "calibration_max": platt["max_samples"],
        "calibration_min_positive": platt["min_positive"],
        "calibration_min_negative": platt["min_negative"],
        "acceptance_samples": config["acceptance"]["samples"],
    }
    for name, configured in spec_bindings.items():
        _same(errors, f"probability.spec.{name}", spec[name], configured)
    for name in ("alpha", "beta"):
        _same(
            errors,
            f"probability.base_rate.{name}",
            _default(beta_smoothed_base_rate, name),
            base[name],
        )
    _same(
        errors,
        "probability.logistic.implementation",
        f"scikit-learn=={runtime_contract_status()['required']}",
        logistic["implementation"],
    )
    model = make_logistic().get_params(deep=False)
    for name in (
        "C",
        "solver",
        "fit_intercept",
        "dual",
        "class_weight",
        "warm_start",
        "tol",
        "max_iter",
        "random_state",
    ):
        _same(errors, f"probability.logistic.{name}", model[name], logistic[name])
    _same(
        errors,
        "probability.platt.regularization",
        _default(fit_platt, "regularization"),
        platt["regularization"],
    )
    _same(errors, "probability.platt.clip_min", apply_platt(-1e9, 1.0, 0.0), platt["clip_min"])
    _same(errors, "probability.platt.clip_max", apply_platt(1e9, 1.0, 0.0), platt["clip_max"])
    acceptance, facts = config["acceptance"], _facts(acceptance_metrics)
    expected = (
        ("positives", "Lt", float(acceptance["min_positive"])),
        ("negatives", "Lt", float(acceptance["min_negative"])),
        ("skill", "GtE", float(acceptance["brier_skill_min"])),
        ("ece", "LtE", float(acceptance["ece_max"])),
    )
    if any(facts[fact] != 1 for fact in expected):
        errors.append("probability.acceptance: executable thresholds differ from config")


def validate_frozen_config(project_dir: str | Path) -> ConfigContractReport:
    """Validate the exact manifests and key executable parameter bindings."""
    root, loaded, versions, errors = Path(project_dir).resolve(), {}, {}, []
    for name, (version_field, version, digest) in _FROZEN.items():
        path = root / "configs" / name
        if not path.is_file():
            raise ConfigContractError(f"Required release configuration is missing: {path}")
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ConfigContractError(f"Configuration must be a mapping: {path}")
        loaded[name], versions[name] = value, str(value.get(version_field))
        if _digest(value) != f"sha256:{digest}":
            errors.append(f"{name}: semantic digest does not match its frozen release")
        if value.get(version_field) != version:
            errors.append(f"{name}.{version_field}: expected {version!r}")
    if not errors:
        _feature_contract(loaded["features_v1.yaml"], errors)
        _state_contract(loaded["state_v1.yaml"], errors)
        _probability_contract(loaded["probability_v1.yaml"], errors)
    if errors:
        raise ConfigContractError(
            "MatVIX frozen configuration contract mismatch; an explicit versioned release "
            "must change the method version and contract:\n  - " + "\n  - ".join(errors)
        )
    bundle = {name: _digest(value) for name, value in loaded.items()}
    return ConfigContractReport(versions, _digest(bundle))
