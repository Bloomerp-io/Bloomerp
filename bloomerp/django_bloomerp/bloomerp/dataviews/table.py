from __future__ import annotations

from django.db.models import QuerySet
from django.http import HttpRequest

from .base import DataviewPagination
from .base import BaseDataviewRenderer


SORT_DIRECTIONS = {"asc", "desc"}


class TableDataviewRenderer(BaseDataviewRenderer):
    template_name = "cotton/ui/data_view/table.html"
    reserved_query_params = {"sort", "direction"}

    def get_context_data(self, pagination) -> dict:
        context = super().get_context_data(pagination)
        context["table_sort_querystring"] = self.build_querystring(
            self.state.request,
            ("page", "sort", "direction"),
        )
        return context

    @staticmethod
    def _get_sortable_fields_by_name(data_view_fields) -> dict:
        if hasattr(data_view_fields, "accessible_fields"):
            return {
                field.field: field
                for field, _is_visible in data_view_fields.accessible_fields
            }

        return {
            field.field: field
            for field in data_view_fields.visible_fields
        }

    @classmethod
    def apply_sorting(
        cls,
        queryset: QuerySet,
        request: HttpRequest,
        data_view_fields,
        options: object | None = None,
    ) -> tuple[QuerySet, dict]:
        sort_field = request.GET.get("sort") or getattr(options, "sort_field", None)
        sort_direction = request.GET.get("direction") or getattr(options, "sort_direction", "asc") or "asc"
        sortable_fields_by_name = cls._get_sortable_fields_by_name(data_view_fields)

        context = {
            "current_sort_field": "",
            "current_sort_direction": "",
        }

        if not sort_field or sort_direction not in SORT_DIRECTIONS:
            return queryset, context

        if sort_field not in sortable_fields_by_name:
            return queryset, context

        sort_expression = sort_field if sort_direction == "asc" else f"-{sort_field}"
        queryset = queryset.order_by(sort_expression, "pk")
        context.update({
            "current_sort_field": sort_field,
            "current_sort_direction": sort_direction,
        })
        return queryset, context

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
