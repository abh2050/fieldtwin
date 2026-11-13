"""Create local bearer tokens for the Gate 8 API, one per role, in .env.app (git-ignored).

    uv run python scripts/app_tokens.py          # keeps existing tokens
    uv run python scripts/app_tokens.py --new    # replaces them

Tokens are random and local. The API keeps only their SHA-256. Gate 9 replaces this with a managed
identity provider; these tokens are never used outside a developer's machine.
"""

from __future__ import annotations

import argparse
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env.app"
PEOPLE = (
    ("local-viewer", "VIEWER"),
    ("local-operator", "OPERATOR"),
    ("local-supervisor", "MAINTENANCE_SUPERVISOR"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--new", action="store_true", help="replace existing tokens")
    args = parser.parse_args()
    if ENV.exists() and not args.new:
        print(f"{ENV.name} exists; keeping its tokens (use --new to replace them).")
    else:
        entries = [f"{actor}:{role}:{secrets.token_urlsafe(24)}" for actor, role in PEOPLE]
        ENV.write_text(f"FIELDTWIN_API_TOKENS={','.join(entries)}\n")
        ENV.chmod(0o600)
        print(f"Wrote {ENV.name}.")
    spec = ENV.read_text().strip().split("=", 1)[1]
    print("Paste one into the app's 'Sign in to act' box:")
    for entry in spec.split(","):
        actor, role, token = entry.split(":", 2)
        print(f"  {role:<24} {actor:<18} {token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
