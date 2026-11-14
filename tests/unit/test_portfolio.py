"""The Gate 10 portfolio can't drift from the evidence it summarizes."""

from __future__ import annotations

import importlib.util
import re
from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INDEX = REPO_ROOT / "docs" / "index.html"


def _summary_module():
    spec = importlib.util.spec_from_file_location(
        "portfolio_summary", REPO_ROOT / "scripts" / "portfolio_summary.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_evaluation_summary_matches_the_result_files():
    committed = (REPO_ROOT / "reports" / "portfolio" / "evaluation_summary.md").read_text()
    assert committed == _summary_module().render(REPO_ROOT), (
        "run: uv run python scripts/portfolio_summary.py"
    )


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name in ("href", "src") and value:
                self.links.append(value)


def test_project_page_links_resolve_inside_the_repository():
    parser = _Links()
    parser.feed(INDEX.read_text())
    local = [
        link.split("#")[0]
        for link in parser.links
        if not link.startswith(("http://", "https://", "#", "mailto:", "data:"))
    ]
    assert local, "the page links to nothing local"
    missing = [link for link in local if link and not (INDEX.parent / link).resolve().exists()]
    assert missing == []


def test_project_page_discloses_the_fiction_and_names_no_ocd_well():
    page = INDEX.read_text()
    assert "fictional" in page.lower()
    assert re.search(r"30-0(15|25)-\d{5}", page) is None  # AGENTS.md rule 10


def test_project_page_figures_come_from_the_generated_summary():
    page = INDEX.read_text()
    summary = (REPO_ROOT / "reports" / "portfolio" / "evaluation_summary.md").read_text()
    figures = re.findall(r'data-source="summary">([^<]+)<', page)
    assert figures, "the page marks its evidence figures with data-source"
    assert [f for f in figures if f not in summary] == []
