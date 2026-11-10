"""Generate inspection requests for fictional assets from stored AETHER prioritization inputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from packages.domain.events import PrioritizationInput
from packages.inspection.requests import request_from_event
from pipelines.acquire.common import core

GOLD = Path("data") / "gold" / "inspection"


def fictional_asset_ids(root: Path) -> set[str]:
    facility = core.load_yaml(root / "config" / "facility" / "aether_field.yaml")
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "asset_id" in node:
                found.add(node["asset_id"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                if isinstance(value, str):
                    found.add(value)
                else:
                    walk(value)

    walk(facility["assets"])
    return found


def run(root: Path = core.REPO_ROOT) -> dict[str, Any]:
    assets = fictional_asset_ids(root)
    inputs = sorted((root / "data" / "gold" / "scenarios").glob("*/*_prioritization_input.json"))
    requests = [
        request_from_event(PrioritizationInput.model_validate_json(path.read_text()), assets)
        for path in inputs
    ]
    out = root / GOLD
    out.mkdir(parents=True, exist_ok=True)
    payload = [r.model_dump(mode="json") for r in sorted(requests, key=lambda r: r.request_id)]
    (out / "inspection_requests.json").write_text(json.dumps(payload, indent=2) + "\n")
    return {"prioritization_inputs": len(inputs), "requests": len(requests)}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
