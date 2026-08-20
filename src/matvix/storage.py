from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd


class ParquetDependencyError(RuntimeError):
    pass


def write_parquet(frame: pd.DataFrame, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, engine="pyarrow", index=False)
        os.replace(temporary, target)
    except ImportError as exc:
        raise ParquetDependencyError(
            "pyarrow is required. Install the locked runtime with: pip install -r requirements.lock"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)
    return target


def read_parquet(path: str | Path) -> pd.DataFrame:
    try:
        return pd.read_parquet(path, engine="pyarrow")
    except ImportError as exc:
        raise ParquetDependencyError(
            "pyarrow is required. Install the locked runtime with: pip install -r requirements.lock"
        ) from exc


def write_json(payload: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(encoded, encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def read_json(path: str | Path) -> dict[str, Any]:
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return loaded
