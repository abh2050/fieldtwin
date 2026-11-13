"""Limit/offset pagination with a total, so a client always knows what it hasn't seen."""

from __future__ import annotations

from typing import Any

from fastapi import Query
from pydantic import BaseModel


class PageParams(BaseModel):
    limit: int
    offset: int


def page_params(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)) -> PageParams:
    return PageParams(limit=limit, offset=offset)


def page(items: list[Any], total: int, params: PageParams) -> dict[str, Any]:
    return {"items": items, "total": total, "limit": params.limit, "offset": params.offset}
