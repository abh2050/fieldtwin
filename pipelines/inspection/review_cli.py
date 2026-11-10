"""Record a human review finding, or list items still pending.

    uv run python -m pipelines.inspection.review_cli pending
    uv run python -m pipelines.inspection.review_cli record CHIP-xxxx INFRASTRUCTURE_VISIBLE --reviewer NAME --feature TANK_BATTERY

Findings are appended to data/gold/inspection/reviews.jsonl. A correction uses --supersedes REVIEW_ID.
"""

from __future__ import annotations

import argparse
import json
import sys

import pandas as pd

from packages.inspection.review import (
    ReviewError,
    ReviewEvent,
    ReviewLedger,
    ReviewOutcome,
    VisibleFeature,
    pending,
)
from pipelines.acquire.common import core

from .evidence import GOLD
from .wells import latest_batch


def chip_ids(root) -> list[str]:
    batch = latest_batch(root, "naip")["batch_id"]
    return sorted(pd.read_parquet(root / "data/bronze/naip" / batch / "chips.parquet")["chip_id"])


def main(argv: list[str] | None = None, root=core.REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("pending")
    record = sub.add_parser("record")
    record.add_argument("evidence_id")
    record.add_argument("outcome", choices=[o.value for o in ReviewOutcome])
    record.add_argument("--reviewer", required=True)
    record.add_argument(
        "--feature",
        action="append",
        default=[],
        choices=[f.value for f in VisibleFeature],
        help="a feature visible in the image; repeat for several",
    )
    record.add_argument("--supersedes")
    args = parser.parse_args(argv)

    ledger = ReviewLedger(root / GOLD / "reviews.jsonl")
    ids = chip_ids(root)
    if args.command == "pending":
        print(
            json.dumps(
                {"pending": pending(ids, ledger), "reviewed": len(ledger.current())}, indent=2
            )
        )
        return 0
    if args.evidence_id not in ids:
        print(f"Unknown evidence ID {args.evidence_id}", file=sys.stderr)
        return 2
    try:
        event = ledger.append(
            ReviewEvent(
                evidence_id=args.evidence_id,
                reviewer=args.reviewer,
                outcome=ReviewOutcome(args.outcome),
                visible_features=tuple(VisibleFeature(f) for f in args.feature),
                supersedes=args.supersedes,
            )
        )
    except (ReviewError, ValueError) as exc:
        print(f"Not recorded: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(event.model_dump(mode="json"), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
