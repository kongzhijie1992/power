"""Dataset and model artifact versioning utilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Optional
import json
import pickle

import pandas as pd


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_file(path: Path) -> str:
    hasher = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def hash_dataframe(frame: pd.DataFrame | pd.Series) -> str:
    if isinstance(frame, pd.Series):
        frame = frame.to_frame("value")
    hashed = pd.util.hash_pandas_object(frame, index=True).values
    hasher = sha256()
    hasher.update(hashed.tobytes())
    return hasher.hexdigest()


def _write_metadata(metadata: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, sort_keys=True)


def record_dataset_version(
    name: str,
    frame: pd.DataFrame | pd.Series,
    output_dir: Path,
    source_path: Optional[Path] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Path:
    data_hash = hash_dataframe(frame)
    if isinstance(frame, pd.Series):
        frame = frame.to_frame("value")
    metadata: Dict[str, Any] = {
        "name": name,
        "hash": data_hash,
        "rows": int(len(frame)),
        "columns": list(frame.columns),
        "index_start": str(frame.index.min()) if len(frame) else None,
        "index_end": str(frame.index.max()) if len(frame) else None,
        "source_path": str(source_path) if source_path else None,
        "created_at": _utc_now(),
    }
    if extra:
        metadata.update(extra)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    metadata_path = output_dir / f"{name}_dataset_{stamp}.json"
    _write_metadata(metadata, metadata_path)
    return metadata_path


def save_model_artifact(
    model: Any,
    output_dir: Path,
    name: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    model_path = output_dir / f"{name}_model_{stamp}.bin"
    if hasattr(model, "save_model"):
        model.save_model(str(model_path))
    else:
        with model_path.open("wb") as handle:
            pickle.dump(model, handle)
    metadata: Dict[str, Any] = {
        "name": name,
        "artifact_path": str(model_path),
        "artifact_hash": hash_file(model_path),
        "created_at": _utc_now(),
        "artifact_type": type(model).__name__,
    }
    if extra:
        metadata.update(extra)
    metadata_path = output_dir / f"{name}_model_{stamp}.json"
    _write_metadata(metadata, metadata_path)
    return {"model_path": model_path, "metadata_path": metadata_path}
