"""Generate data quality reports for every source with a completed batch."""

from __future__ import annotations

import sys

from pipelines.acquire.common.core import REPO_ROOT

from . import nm_ocd, petrobras_3w


def main() -> int:
    failed = False
    for name, module in (("nm_ocd", nm_ocd), ("petrobras_3w", petrobras_3w)):
        try:
            print(f"{name}: {module.profile(REPO_ROOT)}")
        except FileNotFoundError as exc:
            print(f"{name}: NOT PROFILED: {exc}", file=sys.stderr)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
