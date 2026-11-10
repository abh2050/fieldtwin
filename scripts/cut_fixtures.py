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
import rasterio
from rasterio.windows import Window

from pipelines.acquire.carbon_mapper.adapter import ASSET_FIELDS, strip_signature
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

    provenance["sources"].update(cut_gate6(root))
    (FIXTURES / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps(provenance, indent=2))


GATE6_PLUMES = 5
GATE6_SCENES = 3
CHIP_PX = 48


def _strip_links(item: dict) -> dict:
    return {k: strip_signature(v) if k in ASSET_FIELDS else v for k, v in item.items()}


def cut_gate6(root: Path) -> dict[str, dict]:
    """Real Carbon Mapper records (non-commercial terms, attribution kept) and one cropped NAIP chip."""
    sources: dict[str, dict] = {}
    cm = latest_complete(root, "carbon_mapper")
    raw = root / "data/raw/carbon_mapper" / cm["source_version"] / cm["batch_id"]
    out = FIXTURES / "carbon_mapper"
    out.mkdir(parents=True, exist_ok=True)
    for name, keep in (("plumes", GATE6_PLUMES), ("scenes", GATE6_SCENES)):
        source = sorted((raw / name).glob("page_*.json"))[0]
        page = json.loads(source.read_text())
        page["items"] = [_strip_links(i) for i in page["items"][:keep]]
        relative = f"carbon_mapper/{name}_page.json"
        (FIXTURES / relative).write_text(json.dumps(page, indent=1) + "\n")
        sources[relative] = {
            "batch_id": cm["batch_id"],
            "cut_from_sha256": sha256_file(source),
            "rows": keep,
        }
    tile = sorted((raw / "tiles").glob("*.mvt"))[0]
    relative = f"carbon_mapper/{tile.name}"
    (FIXTURES / relative).write_bytes(tile.read_bytes())
    sources[relative] = {
        "batch_id": cm["batch_id"],
        "cut_from_sha256": sha256_file(tile),
        "rows": None,
    }

    naip = latest_complete(root, "naip")
    chips = pq.read_table(
        root / "data/bronze/naip" / naip["batch_id"] / "chips.parquet"
    ).to_pandas()
    control = chips[chips["selection_group"] == "CONTROL"].sort_values("chip_id").iloc[0]
    source = root / control["path"]
    # NAIP licensing for 2022 imagery is unconfirmed, so the pixel crop stays local and uncommitted.
    relative = "naip/chip.tif"
    (FIXTURES / "naip").mkdir(parents=True, exist_ok=True)
    (LOCAL_FIXTURES / "naip").mkdir(parents=True, exist_ok=True)
    with rasterio.open(source) as src:
        window = Window(0, 0, CHIP_PX, CHIP_PX)
        profile = {
            **src.profile,
            "width": CHIP_PX,
            "height": CHIP_PX,
            "transform": src.window_transform(window),
        }
        with rasterio.open(LOCAL_FIXTURES / relative, "w", **profile) as dst:
            dst.write(src.read(window=window))
    sources[relative] = {
        "batch_id": naip["batch_id"],
        "cut_from_sha256": sha256_file(source),
        "rows": None,
    }
    raw_naip = root / "data/raw/naip" / naip["batch_id"].split("-")[1] / naip["batch_id"]
    item = raw_naip / "stac" / f"{control['stac_item_id']}.json"
    (FIXTURES / "naip" / "stac_item.json").write_bytes(item.read_bytes())
    sources["naip/stac_item.json"] = {
        "batch_id": naip["batch_id"],
        "cut_from_sha256": sha256_file(item),
        "rows": 1,
    }
    return sources


if __name__ == "__main__":
    main()
