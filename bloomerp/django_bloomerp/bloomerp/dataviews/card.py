from __future__ import annotations

from django.db.models import QuerySet
from django.http import HttpRequest

from .base import BaseDataviewRenderer
from .base import DataviewPagination


class CardDataviewRenderer(BaseDataviewRenderer):
    template_name = "cotton/features/dataviews/card.html"

    @classmethod
    def paginate_queryset(
        cls,
        queryset: QuerySet,
        _preference,
        request: HttpRequest,
        options: object | None = None,
    ) -> DataviewPagination:
        page_size = int(getattr(options, "page_size", 25))
        page_obj = cls.paginate_object_list(queryset, page_size, request.GET.get("page", 1))
        return DataviewPagination(
            queryset=page_obj,
            page_obj=page_obj,
            pagination_pages=cls.build_pagination_range(page_obj),
            show_global_pagination=True,
        )
