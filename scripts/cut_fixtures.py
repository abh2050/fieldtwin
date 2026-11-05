"""Cut small offline test fixtures from the real acquired batches.

Values are unchanged. The only edits are truncation to a few rows and the XML closing tag this
requires. Run after `make acquire`.

3W samples (CC BY 4.0) are committed. OCD samples go to data/fixtures_local/, which is gitignored,
because OCD states no redistribution terms. CI uses hand-written OCD-shaped rows instead.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pyarrow.parquet as pq

from pipelines.acquire.common.core import REPO_ROOT, sha256_file
from pipelines.profile.common import latest_complete

FIXTURES = REPO_ROOT / "data" / "fixtures"
LOCAL_FIXTURES = REPO_ROOT / "data" / "fixtures_local"
XML_ROWS = 25
ARCGIS_ROWS = 25
PARQUET_ROWS = 300


def cut_xml(source: Path, member: str, tag: str, dest: Path) -> int:
    """Keep the schema preamble and the first rows, as original text."""
    closing = f"</{tag}>"
    with zipfile.ZipFile(source) as archive, archive.open(member) as stream:
        text = stream.read(400_000).decode("utf-16", errors="ignore")
    end, count = text.find("</xsd:schema>"), 0
    while count < XML_ROWS:
        end = text.index(closing, end + 1)
        count += 1
    body = text[: end + len(closing)] + "</root>"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, body.encode("utf-16"))
    return count


def main() -> None:
    root = REPO_ROOT
    ocd = latest_complete(root, "nm_ocd")
    raw = root / "data/raw/nm_ocd" / ocd["source_version"] / ocd["batch_id"]
    provenance = {
        "note": "Real records truncated to a few rows. Values are unchanged. Not for analysis.",
        "sources": {},
    }

    for name, tag in (("wellhistory", "wellhistory"), ("wcproduction", "wcproduction")):
        source = raw / "ftp" / f"{name}.zip"
        cut_xml(source, f"{name}.xml", tag, LOCAL_FIXTURES / "nm_ocd" / f"{name}.zip")

    page = json.loads(sorted((raw / "arcgis").glob("page_*.json"))[0].read_text())
    page["features"] = page["features"][:ARCGIS_ROWS]
    (LOCAL_FIXTURES / "nm_ocd" / "arcgis_page.json").write_text(json.dumps(page))

    w3 = latest_complete(root, "petrobras_3w")
    raw_3w = root / "data/raw/petrobras_3w" / w3["source_version"] / w3["batch_id"]
    (FIXTURES / "petrobras_3w").mkdir(parents=True, exist_ok=True)
    for pattern in ("dataset/2/WELL-*", "dataset/2/SIMULATED_*", "dataset/7/DRAWN_*"):
        source = sorted(raw_3w.glob(pattern + ".parquet"))[0]
        table = pq.read_table(source).slice(0, PARQUET_ROWS)
        relative = f"petrobras_3w/{source.parent.name}_{source.name}"
        pq.write_table(table, FIXTURES / relative, compression="zstd")
        provenance["sources"][relative] = {
            "batch_id": w3["batch_id"],
            "cut_from_sha256": sha256_file(source),
            "rows": table.num_rows,
        }
    (FIXTURES / "petrobras_3w" / "dataset.ini").write_bytes(
        (raw_3w / "dataset/dataset.ini").read_bytes()
    )

    (FIXTURES / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps(provenance, indent=2))


if __name__ == "__main__":
    main()
