from __future__ import annotations

from django.core.exceptions import FieldDoesNotExist
from django.db.models import QuerySet
from django.http import HttpRequest

from ..definition import BaseDataviewRenderer, DataviewPagination


SORT_DIRECTIONS = {"asc", "desc"}


class TableDataviewRenderer(BaseDataviewRenderer):
    template_name = "cotton/features/dataviews/table.html"
    reserved_query_params = {"sort", "direction"}

    def get_context_data(self, pagination) -> dict:
        context = super().get_context_data(pagination)
        context["table_sort_querystring"] = self.build_querystring(
            self.state.request,
            ("page", "sort", "direction"),
        )
        return context

    @staticmethod
    def _get_sortable_fields_by_name(queryset: QuerySet, dataview_fields) -> dict:
        if hasattr(dataview_fields, "accessible_fields"):
            application_fields = [
                field
                for field, _is_visible in dataview_fields.accessible_fields
            ]
        else:
            application_fields = list(dataview_fields.visible_fields)

        sortable_fields = {}
        for application_field in application_fields:
            try:
                model_field = queryset.model._meta.get_field(application_field.field)
            except FieldDoesNotExist:
                continue

            if getattr(model_field, "concrete", False):
                sortable_fields[application_field.field] = application_field

        return sortable_fields

    @classmethod
    def apply_sorting(
        cls,
        queryset: QuerySet,
        request: HttpRequest,
        dataview_fields,
        options: object | None = None,
    ) -> tuple[QuerySet, dict]:
        sort_field = request.GET.get("sort") or getattr(options, "sort_field", None)
        sort_direction = request.GET.get("direction") or getattr(options, "sort_direction", "asc") or "asc"
        sortable_fields_by_name = cls._get_sortable_fields_by_name(queryset, dataview_fields)

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
