from typing import Optional

from fastapi import Query, Response


class Pagination:
    """Optional ?limit=&offset= on list endpoints.

    With no limit the endpoint behaves exactly as before. With a limit, the page is
    returned and the full match count is sent in the X-Total-Count header.
    """

    def __init__(
        self,
        limit: Optional[int] = Query(None, ge=1, le=1000, description="Page size (max 1000)"),
        offset: int = Query(0, ge=0),
    ):
        self.limit = limit
        self.offset = offset

    def apply(self, query, response: Response, order_by=None):
        if self.limit is None:
            return query
        response.headers["X-Total-Count"] = str(query.count())
        if order_by is not None:
            query = query.order_by(order_by)
        return query.limit(self.limit).offset(self.offset)
