"""Retrying network clients. Exhausted retries become SourceUnavailable, never empty results."""

from __future__ import annotations

import ftplib
import json
import os
from pathlib import Path
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .errors import MalformedSource, SourceUnavailable

_TRANSIENT = (OSError, EOFError, ftplib.Error, httpx.TransportError, httpx.HTTPStatusError)
_retrying = retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    retry=retry_if_exception_type(_TRANSIENT),
    reraise=True,
)
USER_AGENT = "fieldtwin-acquisition/0.1 (bounded research download)"


class Http:
    def __init__(self, timeout: float = 120.0):
        self.client = httpx.Client(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}
        )

    @_retrying
    def _get(self, url: str, params: dict[str, Any] | None) -> httpx.Response:
        response = self.client.get(url, params=params)
        response.raise_for_status()
        return response

    def get_bytes(self, url: str, params: dict[str, Any] | None = None) -> bytes:
        try:
            return self._get(url, params).content
        except _TRANSIENT as exc:
            raise SourceUnavailable(f"GET {url} failed: {exc}") from exc

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        body = self.get_bytes(url, params)
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise MalformedSource(f"{url} did not return JSON") from exc
        # ArcGIS reports errors in a 200 response, so an unchecked read would look like no data.
        if isinstance(payload, dict) and "error" in payload:
            raise SourceUnavailable(f"{url} returned an error: {payload['error']}")
        return payload


class Ftp:
    """Anonymous FTP with resume. FTP has no integrity check, so size and timestamp are compared."""

    def __init__(self, host: str, timeout: float = 120.0):
        self.host = host
        self.timeout = timeout

    def _connect(self) -> ftplib.FTP:
        connection = ftplib.FTP(self.host, timeout=self.timeout)
        connection.login()
        connection.voidcmd("TYPE I")
        return connection

    @_retrying
    def _stat(self, path: str) -> tuple[int, str]:
        with self._connect() as connection:
            size = connection.size(path)
            modified = connection.voidcmd(f"MDTM {path}").split()[-1]
        if size is None:
            raise ftplib.error_perm(f"no size reported for {path}")
        return size, modified

    def stat(self, path: str) -> tuple[int, str]:
        """Return (size in bytes, modified timestamp as YYYYMMDDHHMMSS)."""
        try:
            return self._stat(path)
        except _TRANSIENT as exc:
            raise SourceUnavailable(f"FTP stat of {path} failed: {exc}") from exc

    @_retrying
    def _retrieve(self, path: str, partial: Path) -> None:
        offset = partial.stat().st_size if partial.exists() else 0
        with self._connect() as connection, partial.open("ab") as handle:
            connection.retrbinary(f"RETR {path}", handle.write, 1 << 20, rest=offset or None)

    def download(self, path: str, dest: Path, size: int, modified: str) -> None:
        """Download to `dest`, resuming a partial file only if upstream has not changed."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = dest.with_name(dest.name + ".part")
        stamp = dest.with_name(dest.name + ".part.modified")
        if partial.exists() and (not stamp.exists() or stamp.read_text() != modified):
            partial.unlink()
        stamp.write_text(modified)
        try:
            self._retrieve(path, partial)
            final_size, final_modified = self._stat(path)
        except (TimeoutError, *_TRANSIENT) as exc:
            raise SourceUnavailable(
                f"FTP download of {path} failed; partial file kept for resume: {exc}"
            ) from exc
        if final_modified != modified:
            partial.unlink(missing_ok=True)
            stamp.unlink(missing_ok=True)
            raise SourceUnavailable(f"{path} changed upstream during download. Re-run to retry.")
        received = partial.stat().st_size
        if received != size or final_size != size:
            partial.unlink(missing_ok=True)
            stamp.unlink(missing_ok=True)
            raise MalformedSource(f"{path}: received {received} bytes, expected {size}.")
        os.replace(partial, dest)
        stamp.unlink(missing_ok=True)
