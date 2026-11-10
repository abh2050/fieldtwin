"""Build evidence cards and a local review page for wells with a NAIP chip.

Writes data/gold/inspection/, which is gitignored: it shows real wells beside real plume records,
and committed files stay aggregate. Two pages are produced:

- review_queue.html is blinded. It shows each chip by an opaque ID and nothing about plumes, so a
  reviewer's reading of the image isn't steered by whether a plume was detected nearby.
- evidence.html shows the full card for each well: coverage, nearby plumes, the chip, attribution,
  and the fixed statements of what the evidence can't show.
"""

from __future__ import annotations

import html
import json
import os
import re
import warnings
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import rasterio
import rasterio.errors

from packages.inspection import claims
from packages.inspection.contracts import CoverageStatus, ImageChip, ProximityLink, WellCoverage
from packages.inspection.evidence import EvidenceCard, build_card
from pipelines.acquire.common import core

from .associate import SILVER, load_rules
from .wells import latest_batch

GOLD = Path("data") / "gold" / "inspection"
_TAGS = re.compile(r"<[^>]+>")


def _float(value: Any) -> float | None:
    return None if value in (None, "", "None") else float(value)


def chip_model(row: dict[str, Any]) -> ImageChip:
    return ImageChip(
        chip_id=row["chip_id"],
        source_asset_id=row["source_asset_id"],
        stac_item_id=row["stac_item_id"],
        acquisition_date=date.fromisoformat(row["acquisition_date"]),
        ground_sample_distance_m=float(row["ground_sample_distance_m"]),
        crs=row["crs"],
        footprint_wgs84=(
            float(row["west"]),
            float(row["south"]),
            float(row["east"]),
            float(row["north"]),
        ),
        source_href=row["source_href"],
        path=row["path"],
        sha256=row["sha256"],
        width_px=int(row["width_px"]),
        height_px=int(row["height_px"]),
        bands=int(row["bands"]),
        selection_group=row["selection_group"],
    )


def build_cards(root: Path) -> tuple[list[EvidenceCard], dict[str, str]]:
    rules = load_rules(root)
    radius = float(rules["association"]["primary_radius_m"])
    silver = root / SILVER
    links = [
        ProximityLink(**r)
        for r in pd.read_parquet(silver / "proximity_links.parquet").to_dict("records")
    ]
    coverage = {
        r["source_asset_id"]: WellCoverage.model_validate(
            {k: (None if pd.isna(v) else v) for k, v in r.items()}
        )
        for r in pd.read_parquet(silver / "coverage.parquet").to_dict("records")
    }
    cm = latest_batch(root, "carbon_mapper")
    plumes = pd.read_parquet(root / "data/bronze/carbon_mapper" / cm["batch_id"] / "plumes.parquet")
    details = {
        p["plume_id"]: {
            "observed_at": datetime.fromisoformat(p["scene_timestamp"].replace("Z", "+00:00")),
            "instrument": p["instrument"],
            "emission_kg_per_h": None
            if p["hide_emission"] == "True"
            else _float(p["emission_auto"]),
            "emission_uncertainty_kg_per_h": None
            if p["hide_emission"] == "True"
            else _float(p["emission_uncertainty_auto"]),
        }
        for p in plumes.to_dict("records")
    }
    quicklooks = {
        p["plume_id"]: p["quicklook_path"]
        for p in plumes.to_dict("records")
        if isinstance(p.get("quicklook_path"), str) and p["quicklook_path"]
    }
    naip = latest_batch(root, "naip")
    chips = pd.read_parquet(root / "data/bronze/naip" / naip["batch_id"] / "chips.parquet")
    by_well: dict[str, list[ProximityLink]] = {}
    for link in links:
        by_well.setdefault(link.source_asset_id, []).append(link)
    cards = [
        build_card(
            coverage[row["source_asset_id"]],
            by_well.get(row["source_asset_id"], []),
            details,
            chip_model(row),
            radius,
        )
        for row in chips.sort_values("chip_id").to_dict("records")
    ]
    return cards, quicklooks


def render_png(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(source) as src:
        rgb = src.read([1, 2, 3])
        profile = {
            "driver": "PNG",
            "width": src.width,
            "height": src.height,
            "count": 3,
            "dtype": "uint8",
        }
    # A PNG preview carries no georeferencing by design; the GeoTIFF chip keeps it.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", rasterio.errors.NotGeoreferencedWarning)
        with rasterio.open(dest, "w", **profile) as out:
            out.write(rgb)


_STYLE = """
:root{--bg:#fbfaf7;--fg:#1c1c1a;--muted:#5d5b55;--line:#dcd8cf;--card:#fff;--warn:#7a4b00}
@media (prefers-color-scheme: dark){:root{--bg:#161614;--fg:#ecebe6;--muted:#a9a69d;--line:#3a3934;--card:#1f1f1c;--warn:#f0c674}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:16px}
.notice{border:1px solid var(--line);border-left:4px solid var(--warn);padding:10px 14px;background:var(--card)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px;margin-top:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:12px}
.card img{width:100%;height:auto;border-radius:4px;display:block}
.muted{color:var(--muted);font-size:13px}
ul{padding-left:18px;margin:6px 0}
"""


def _page(title: str, body: str) -> str:
    return (
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
        f"content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title>"
        f"<style>{_STYLE}</style></head><body><main>{body}</main></body></html>"
    )


def _rel(target: Path, page_dir: Path) -> str:
    return html.escape(os.path.relpath(target, page_dir))


def render_pages(
    root: Path, cards: list[EvidenceCard], quicklooks: dict[str, str]
) -> dict[str, Path]:
    out = root / GOLD
    png_dir = out / "chips"
    for card in cards:
        assert card.chip is not None
        render_png(root / card.chip.path, png_dir / f"{card.chip.chip_id}.png")

    limits = "".join(f"<li>{html.escape(t)}</li>" for t in cards[0].limits) if cards else ""
    queue = "".join(
        f"<div class='card'><img alt='NAIP image {c.chip.chip_id}' src='{_rel(png_dir / f'{c.chip.chip_id}.png', out)}'>"
        f"<p><strong>{c.chip.chip_id}</strong></p><p class='muted'>{html.escape(c.chip_caption or '')}</p></div>"
        for c in cards
        if c.chip
    )
    queue_page = _page(
        "Blinded Review Queue",
        "<h1>Blinded image review</h1><div class='notice'><p>Images are shown by opaque ID only. "
        "Nothing about nearby plumes is shown, so the reading of each image is independent of it. "
        "Record findings with <code>make inspection-review</code>.</p>"
        f"<ul>{limits}</ul><p class='muted'>{html.escape(cards[0].attributions[-1]) if cards else ''}</p></div>"
        f"<div class='grid'>{queue}</div>",
    )

    blocks = []
    for card in cards:
        assert card.chip is not None
        plumes = "".join(
            "<li>"
            + html.escape(p.caption)
            + (
                f" <span class='muted'>Published estimate {p.emission_kg_per_h:.0f} kg/h, "
                f"uncertainty {p.emission_uncertainty_kg_per_h:.0f} kg/h (statistical meaning not stated).</span>"
                if p.emission_kg_per_h is not None and p.emission_uncertainty_kg_per_h is not None
                else ""
            )
            + (
                f"<br><img alt='Carbon Mapper quicklook {html.escape(p.plume_id)}' style='max-width:180px' "
                f"src='{_rel(root / quicklooks[p.plume_id], out)}'>"
                if p.plume_id in quicklooks
                else ""
            )
            + "</li>"
            for p in card.plumes
        )
        blocks.append(
            f"<div class='card'><img alt='NAIP image {card.chip.chip_id}' "
            f"src='{_rel(png_dir / f'{card.chip.chip_id}.png', out)}'>"
            f"<p><strong>{html.escape(card.headline)}</strong></p>"
            f"<p>{html.escape(card.coverage_text)}</p><ul>{plumes}</ul>"
            f"<p class='muted'>{html.escape(card.chip_caption or '')}</p>"
            f"<p class='muted'>{' · '.join(html.escape(a) for a in card.attributions)}</p></div>"
        )
    evidence_page = _page(
        "Aerial Evidence",
        "<h1>Aerial evidence for registry wells</h1><div class='notice'><p>Real public records, shown for "
        "review. Local only; not for distribution.</p>"
        f"<ul>{limits}</ul></div><div class='grid'>{''.join(blocks)}</div>",
    )
    paths = {"review_queue": out / "review_queue.html", "evidence": out / "evidence.html"}
    paths["review_queue"].write_text(queue_page)
    paths["evidence"].write_text(evidence_page)
    for path in paths.values():
        check_rendered(path.read_text())
    return paths


def visible_sentences(page: str) -> list[str]:
    text = html.unescape(_TAGS.sub("\n", page))
    return [line.strip() for line in text.splitlines() if line.strip()]


def check_rendered(page: str) -> int:
    """Run the claim guard over every visible line of a rendered page. Returns lines checked."""
    lines = visible_sentences(page)
    for line in lines:
        claims.check(line)
    return len(lines)


def run(root: Path = core.REPO_ROOT) -> dict[str, Any]:
    cards, quicklooks = build_cards(root)
    paths = render_pages(root, cards, quicklooks)
    (root / GOLD / "evidence_cards.json").write_text(
        json.dumps([c.model_dump(mode="json") for c in cards], indent=1) + "\n"
    )
    checked = sum(check_rendered(p.read_text()) for p in paths.values())
    groups = pd.Series([c.chip.selection_group for c in cards if c.chip]).value_counts().to_dict()
    statuses = pd.Series([c.coverage_status.value for c in cards]).value_counts().to_dict()
    return {
        "cards": len(cards),
        "chips_by_group": groups,
        "card_coverage_status": statuses,
        "cards_with_plume_quicklook": sum(
            1 for c in cards if any(p.plume_id in quicklooks for p in c.plumes)
        ),
        "rendered_lines_checked": checked,
        "claim_violations": 0,
        "pages": {k: core.rel(v, root) for k, v in paths.items()},
        "coverage_status_values": [s.value for s in CoverageStatus],
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
