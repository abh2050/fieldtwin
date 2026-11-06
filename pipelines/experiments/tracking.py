"""Local MLflow tracking. The store and artifacts stay in the gitignored data folder."""

from __future__ import annotations

import glob
import hashlib
import json
import logging
import tempfile
from pathlib import Path

import mlflow

from pipelines.experiments.common import EXPERIMENTS

STORE = EXPERIMENTS / "mlflow"


def _experiment(name: str) -> None:
    STORE.mkdir(parents=True, exist_ok=True)
    logging.getLogger("mlflow").setLevel(logging.WARNING)
    mlflow.set_tracking_uri(f"sqlite:///{STORE / 'mlflow.db'}")
    if mlflow.get_experiment_by_name(name) is None:
        mlflow.create_experiment(name, artifact_location=(STORE / "artifacts" / name).as_uri())
    mlflow.set_experiment(name)


def source_manifests(source: str) -> dict[str, str]:
    """Checksums of the acquisition manifests behind a dataset."""
    root = Path(__file__).resolve().parents[2]
    found = {}
    for path in sorted(glob.glob(str(root / "data" / "manifests" / f"*{source}*"))):
        found[Path(path).name] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return found


def log_run(*, experiment: str, run_name: str, params: dict, metrics: dict, documents: dict, artifact: Path, artifact_sha256: str) -> str:
    _experiment(experiment)
    with mlflow.start_run(run_name=run_name) as run:
        for key, value in params.items():
            mlflow.log_param(key, json.dumps(value) if isinstance(value, dict | list) else value)
        mlflow.log_param("artifact_sha256", artifact_sha256)
        for key, value in metrics.items():
            if isinstance(value, int | float) and not isinstance(value, bool) and value == value:
                mlflow.log_metric(key, float(value))
        with tempfile.TemporaryDirectory() as folder:
            for name, payload in documents.items():
                path = Path(folder) / name
                path.write_text(json.dumps(payload, indent=1, default=str))
                mlflow.log_artifact(str(path), "documents")
        mlflow.log_artifact(str(artifact), "model")
        return run.info.run_id
