from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


@lru_cache(maxsize=8)
def _validate_project_release(root: str) -> None:
    # Import locally so config parsing itself stays usable by the validator and
    # module import order cannot create a cycle.
    from matvix.config_contract import validate_frozen_config

    validate_frozen_config(Path(root))


def project_root() -> Path:
    """Resolve the active MatVIX project without embedding a private machine path.

    Resolution order is explicit environment override, a checkout-like current
    directory, then the source checkout root. This keeps CLI defaults usable
    both for Codex local rebuilds and editable installs.
    """

    override = os.environ.get("MATVIX_PROJECT_DIR")
    if override:
        root = Path(override).expanduser().resolve()
    else:
        cwd = Path.cwd().resolve()
        if (cwd / "configs").is_dir() and (cwd / "schemas").is_dir():
            root = cwd
        else:
            checkout = Path(__file__).resolve().parents[2]
            root = (
                checkout
                if (checkout / "configs").is_dir() and (checkout / "schemas").is_dir()
                else cwd
            )
    _validate_project_release(str(root))
    return root


def load_yaml(name_or_path: str | Path) -> dict[str, Any]:
    path = Path(name_or_path)
    if not path.exists():
        path = project_root() / "configs" / str(name_or_path)
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"Configuration must be a mapping: {path}")
    return loaded
