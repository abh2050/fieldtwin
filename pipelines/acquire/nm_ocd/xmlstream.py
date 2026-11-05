"""Stream rows out of OCD's zipped XML without extracting it.

The files are UTF-16 SQL Server exports that compress about 20:1, so `wcproduction.xml` is far
larger than the zip. Rows are parsed as they are decompressed and never written to disk whole.
"""

from __future__ import annotations

import zipfile
import zlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from xml.parsers import expat

from pipelines.acquire.common.errors import MalformedSource

_CHUNK = 1 << 20


def iter_rows(zip_path: Path, member: str, row_tag: str) -> Iterator[dict[str, str | None]]:
    """Yield each row as {column: original text}. Nil elements become None, empty stay ''."""
    rows: list[dict[str, str | None]] = []
    current: Any = None
    column: Any = None
    is_nil = False
    text: list[str] = []

    def start(name: str, attrs: dict[str, str]) -> None:
        nonlocal current, column, is_nil
        if name == row_tag:
            current = {}
        elif current is not None:
            column = name
            is_nil = attrs.get("xsi:nil") == "true"
            text.clear()

    def end(name: str) -> None:
        nonlocal current, column
        if name == row_tag:
            rows.append(current)
            current = None
        elif current is not None:
            current[column] = None if is_nil else "".join(text)
            column = None

    def characters(data: str) -> None:
        if column is not None:
            text.append(data)

    parser = expat.ParserCreate()
    parser.buffer_text = True
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = characters

    try:
        with zipfile.ZipFile(zip_path) as archive, archive.open(member) as stream:
            while chunk := stream.read(_CHUNK):
                parser.Parse(chunk, False)
                yield from rows
                rows.clear()
            parser.Parse(b"", True)
            yield from rows
    except (zipfile.BadZipFile, zlib.error, EOFError, KeyError) as exc:
        raise MalformedSource(f"{zip_path.name}: damaged or truncated archive: {exc}") from exc
    except expat.ExpatError as exc:
        raise MalformedSource(f"{zip_path.name}: malformed XML: {exc}") from exc
