"""Run one source adapter. A failure writes a report and exits 1; no data is substituted."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any

from pipelines.acquire.carbon_mapper import adapter as carbon_mapper
from pipelines.acquire.common import core
from pipelines.acquire.common.errors import AcquisitionError
from pipelines.acquire.naip import adapter as naip
from pipelines.acquire.nm_ocd import adapter as nm_ocd
from pipelines.acquire.petrobras_3w import adapter as petrobras_3w

ADAPTERS: dict[str, Callable[..., dict[str, Any]]] = {
    "carbon_mapper": carbon_mapper.run,
    "naip": naip.run,
    "nm_ocd": nm_ocd.run,
    "petrobras_3w": petrobras_3w.run,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=sorted(ADAPTERS))
    parser.add_argument("--refresh", action="store_true", help="ignore a completed batch")
    args = parser.parse_args(argv)
    try:
        manifest = ADAPTERS[args.source](refresh=args.refresh)
    except (AcquisitionError, OSError) as exc:
        path = core.write_failure_report(core.REPO_ROOT, args.source, None, "acquire", exc)
        print(f"FAILED {args.source}: {exc}\nReport: {path}", file=sys.stderr)
        return 1
    summary = {
        k: manifest.get(k)
        for k in ("batch_id", "processing_status", "accepted_count", "rejected_count", "reused")
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
