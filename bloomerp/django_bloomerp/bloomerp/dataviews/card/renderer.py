from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import QuerySet
from django.http import HttpRequest

from ..definition import BaseDataviewRenderer, DataviewPagination

if TYPE_CHECKING:
    from bloomerp.models.users.user_list_view_preference import UserListViewPreference


class CardDataviewRenderer(BaseDataviewRenderer):
    template_name = "dataview/card/body.html"
    item_template_name = "dataview/card/item.html"

    @classmethod
    def paginate_queryset(
        cls,
        queryset: QuerySet,
        _preference: UserListViewPreference,
        request: HttpRequest,
        options: object | None = None,
    ) -> DataviewPagination:
        """Paginate cards, using primary-key order when the queryset is unordered."""
        if not queryset.ordered:
            queryset = queryset.order_by("pk")
        page_size = int(getattr(options, "page_size", 25))
        page_obj = cls.paginate_object_list(queryset, page_size, request.GET.get("page", 1))
        return DataviewPagination(
            queryset=page_obj,
            page_obj=page_obj,
            pagination_pages=cls.build_pagination_range(page_obj),
            show_global_pagination=True,
        )
