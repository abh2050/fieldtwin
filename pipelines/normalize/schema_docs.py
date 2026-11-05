"""Generate schema documentation from the live catalog, so it can't drift from what was migrated."""

from __future__ import annotations

import sys

import psycopg

from packages.repositories.database import REPO_ROOT, connect

OUTPUT = REPO_ROOT / "reports" / "data_quality" / "canonical_schema.md"
HIDDEN = {"spatial_ref_sys", "schema_migrations"}


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_schema_doc(conn: psycopg.Connection) -> str:
    tables = conn.execute(
        """SELECT c.relname, c.relkind::text, coalesce(obj_description(c.oid, 'pg_class'), '')
           FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'public' AND c.relkind IN ('r', 'v')
             AND c.relname NOT IN ('geometry_columns', 'geography_columns')
           ORDER BY c.relkind, c.relname"""
    ).fetchall()
    base = [t for t in tables if t[1] == "r" and t[0] not in HIDDEN]
    views = [t for t in tables if t[1] == "v"]
    lines = [
        "# Canonical schema",
        "",
        "Generated from the PostgreSQL catalog by `make schema-docs`. A test fails if this file differs from a freshly migrated database.",
        "",
        f"{len(base)} tables and {len(views)} views. DDL lives in [`db/migrations/`](../../db/migrations/), with a full dump in [`db/ddl/schema.sql`](../../db/ddl/schema.sql).",
        "",
        "AETHER Field is fictional. Real source entities live in `source_assets` and fictional ones in `assets`, and no foreign key lets one stand in for the other.",
        "",
        "## Enumerations",
        "",
    ]
    for name, values in conn.execute(
        """SELECT t.typname, string_agg(e.enumlabel, ', ' ORDER BY e.enumsortorder)
           FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid
           JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'public'
           GROUP BY t.typname ORDER BY t.typname"""
    ):
        lines.append(f"- `{name}`: {values}")
    lines += ["", "## Tables", ""]
    for table, _, comment in base:
        lines += [f"### `{table}`", ""]
        if comment:
            lines += [comment, ""]
        lines += ["| Column | Type | Null | Description |", "|---|---|---|---|"]
        for column, kind, nullable, description in conn.execute(
            """SELECT a.attname, format_type(a.atttypid, a.atttypmod),
                      CASE WHEN a.attnotnull THEN 'no' ELSE 'yes' END,
                      coalesce(col_description(a.attrelid, a.attnum), '')
               FROM pg_attribute a WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped
               ORDER BY a.attnum""",
            (table,),
        ):
            lines.append(f"| `{column}` | {_cell(kind)} | {nullable} | {_cell(description)} |")
        constraints = conn.execute(
            """SELECT conname, contype::text FROM pg_constraint WHERE conrelid = %s::regclass
               ORDER BY contype, conname""",
            (table,),
        ).fetchall()
        kinds = {
            "p": "primary key",
            "f": "foreign key",
            "u": "unique",
            "c": "check",
            "x": "exclusion",
        }
        grouped: dict[str, list[str]] = {}
        for name, kind in constraints:
            grouped.setdefault(kinds.get(str(kind), str(kind)), []).append(name)
        lines.append("")
        for kind in ("check", "exclusion"):
            if kind in grouped:
                lines.append(
                    f"{kind.capitalize()} constraints: "
                    + ", ".join(f"`{n}`" for n in grouped[kind])
                    + "."
                )
        summary = [
            f"{len(grouped.get(k, []))} {k}" for k in ("primary key", "foreign key", "unique")
        ]
        lines += [f"Keys: {', '.join(summary)}.", ""]
    triggers = conn.execute(
        """SELECT c.relname, t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
           JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'public' AND NOT t.tgisinternal ORDER BY 1, 2"""
    ).fetchall()
    lines += ["## Triggers", "", "| Table | Trigger |", "|---|---|"]
    lines += [f"| `{table}` | `{name}` |" for table, name in triggers]
    lines += ["", "## Views", ""]
    for view, _, comment in views:
        lines.append(f"- `{view}`" + (f": {comment}" if comment else ""))
    return "\n".join(lines) + "\n"


def main() -> int:
    with connect() as conn:
        OUTPUT.write_text(render_schema_doc(conn))
    print(f"wrote {OUTPUT.relative_to(REPO_ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
