from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query

DEFAULT_PAGE = 1
DEFAULT_PER_PAGE = 20


@dataclass(frozen=True, kw_only=True)
class PageQuery:
    page: int
    per_page: int


def _query(
    page: Annotated[int, Query(ge=1)] = DEFAULT_PAGE,
    per_page: Annotated[int, Query(ge=1)] = DEFAULT_PER_PAGE,
) -> PageQuery:
    return PageQuery(page=page, per_page=per_page)


Page = Annotated[PageQuery, Depends(_query)]


def page_bounds(query: PageQuery) -> slice:
    start = (query.page - 1) * query.per_page
    return slice(start, start + query.per_page)


def page_meta(total: int, query: PageQuery) -> dict[str, int]:
    return {
        "page": query.page,
        "per_page": query.per_page,
        "total": total,
        "total_pages": (total + query.per_page - 1) // query.per_page,
    }
