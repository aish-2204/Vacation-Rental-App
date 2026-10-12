"""Template Method for paginated list endpoints.

`PageQuery.fetch` fixes the algorithm (count, guard the offset, load one ordered
page, map rows, build the envelope). Subclasses supply only the varying steps:
which rows (`statement`), their order (`order_by`), and how a row becomes a
response item (`to_item`, or `to_items` for batch mapping).
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.common import Paginated, Pagination


def pagination(page: int, page_size: int, total: int) -> Pagination:
    return Pagination(
        page=page,
        page_size=page_size,
        total_items=total,
        total_pages=(total + page_size - 1) // page_size,
    )


class PageQuery[Row, Item](ABC):
    @abstractmethod
    def statement(self) -> Select:
        """Filtered rows, without ordering or limits."""

    @abstractmethod
    def order_by(self) -> Sequence[Any]:
        """Stable ordering: always end with a unique column such as the ID."""

    def to_item(self, row: Row) -> Item:
        raise NotImplementedError

    def to_items(self, rows: Sequence[Row]) -> list[Item]:
        return [self.to_item(row) for row in rows]

    async def fetch(self, session: AsyncSession, page: int, page_size: int) -> Paginated[Item]:
        statement = self.statement()
        total = await session.scalar(select(func.count()).select_from(statement.subquery()))
        offset = (page - 1) * page_size
        rows: Sequence[Row] = []
        # An arbitrarily large out-of-range page is still an empty page; do not
        # overflow PostgreSQL's bigint OFFSET parameter for valid positive integers.
        if offset < total:
            rows = (
                await session.scalars(
                    statement.order_by(*self.order_by()).offset(offset).limit(page_size)
                )
            ).all()
        return Paginated(data=self.to_items(rows), pagination=pagination(page, page_size, total))
