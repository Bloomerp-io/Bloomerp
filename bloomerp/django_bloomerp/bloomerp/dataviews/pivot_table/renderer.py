from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable

from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.models import Avg, Count, Max, Min, Q, QuerySet, Sum
from django.db.models.functions import Cast
from django.http import HttpRequest

from bloomerp.models.application_field import ApplicationField
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager, create_permission_str
from bloomerp.utils.labels import safe_object_label

from ..definition import BaseDataviewRenderer, DataviewPagination


NUMERIC_FIELD_TYPES = (
    models.IntegerField,
    models.FloatField,
    models.DecimalField,
    models.DurationField,
)
NUMERIC_AGGREGATIONS = {"count", "sum", "min", "max", "avg"}
BOOLEAN_AGGREGATIONS = {"count", "sum"}
MAX_PIVOT_LEAF_COLUMNS = 100


class PivotTableTooWide(Exception):
    """Raised when a pivot would render an unsafe number of columns."""


def _hashable(value: Any) -> Any:
    """Convert database values such as JSON lists/dicts into stable path keys."""
    if isinstance(value, dict):
        return tuple(sorted((str(key), _hashable(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple, set)):
        return tuple(_hashable(item) for item in value)
    return value


@dataclass(frozen=True)
class PivotField:
    """One model-backed field used by a reusable pivot definition."""

    name: str
    title: str
    model_field: models.Field


@dataclass(frozen=True)
class PivotValueField(PivotField):
    """A pivot value field paired with its requested aggregation."""

    aggregation: str = "count"


@dataclass(frozen=True)
class PivotHeaderCell:
    label: str
    colspan: int


@dataclass
class PivotRow:
    """One flattened row in the expandable pivot hierarchy."""

    path: tuple[Any, ...]
    raw_path: tuple[Any, ...]
    label: str
    depth: int
    values_by_column: dict[tuple[Any, ...], Any] = field(default_factory=dict)
    totals: list[Any] = field(default_factory=list)
    children: list["PivotRow"] = field(default_factory=list)
    row_id: str = ""
    parent_id: str = ""
    cells: list[Any] = field(default_factory=list)

    @property
    def has_children(self) -> bool:
        return bool(self.children)


@dataclass
class PivotTableResult:
    """Template-ready result produced from database aggregate queries."""

    header_rows: list[list[PivotHeaderCell]]
    value_headers: list[str]
    rows: list[PivotRow]
    column_totals: list[Any]
    grand_totals: list[Any]
    effective_aggregations: list[str]


@dataclass
class PivotTable:
    """Reusable, database-backed pivot-table query and rendering model.

    The class performs aggregation with Django ORM expressions and only assembles
    the already-aggregated result into header and row hierarchies in Python.
    """

    queryset: QuerySet
    row_fields: list[PivotField]
    column_fields: list[PivotField]
    value_fields: list[PivotValueField]
    show_row_totals: bool = True
    show_column_totals: bool = True
    totals_scope: str = "page"
    _related_labels: dict[tuple[str, Any], str] = field(default_factory=dict, init=False)

    def build(self, top_level_values: Iterable[Any]) -> PivotTableResult:
        effective_aggregations = [
            self._effective_aggregation(value_field)
            for value_field in self.value_fields
        ]
        value_headers = [
            self._value_header(value_field, effective_aggregations[value_index])
            for value_index, value_field in enumerate(self.value_fields)
        ]
        aggregate_expressions = self._aggregate_expressions(effective_aggregations)
        page_queryset = self._filter_top_level_rows(top_level_values)
        column_paths, raw_column_paths = self._column_paths()
        self._prepare_related_labels()
        leaf_column_paths = [
            (*column_path, value_index)
            for column_path in column_paths
            for value_index in range(len(self.value_fields))
        ]
        nodes_by_path: dict[tuple[Any, ...], PivotRow] = {}
        root_rows: list[PivotRow] = []

        for depth in range(len(self.row_fields)):
            row_fields = self.row_fields[: depth + 1]
            group_names = [item.name for item in row_fields + self.column_fields]
            grouped = (
                page_queryset.values(*group_names)
                .annotate(**aggregate_expressions)
                .order_by(*group_names)
            )

            for item in grouped:
                raw_row_path = tuple(item[pivot_field.name] for pivot_field in row_fields)
                row_path = tuple(_hashable(value) for value in raw_row_path)
                node = nodes_by_path.get(row_path)
                if node is None:
                    node = PivotRow(
                        path=row_path,
                        raw_path=raw_row_path,
                        label=self._format_dimension_value(row_fields[-1], raw_row_path[-1]),
                        depth=depth,
                    )
                    nodes_by_path[row_path] = node
                    if depth == 0:
                        root_rows.append(node)
                    else:
                        parent = nodes_by_path.get(row_path[:-1])
                        if parent is not None:
                            parent.children.append(node)

                raw_column_path = tuple(
                    item[pivot_field.name] for pivot_field in self.column_fields
                )
                column_path = tuple(_hashable(value) for value in raw_column_path)
                for value_index in range(len(self.value_fields)):
                    node.values_by_column[(*column_path, value_index)] = item[
                        f"pivot_value_{value_index}"
                    ]

            if self.show_row_totals:
                totals = (
                    page_queryset.values(*(item.name for item in row_fields))
                    .annotate(**aggregate_expressions)
                    .order_by()
                )
                for item in totals:
                    row_path = tuple(
                        _hashable(item[pivot_field.name]) for pivot_field in row_fields
                    )
                    if row_path in nodes_by_path:
                        nodes_by_path[row_path].totals = [
                            item[f"pivot_value_{value_index}"]
                            for value_index in range(len(self.value_fields))
                        ]

        flattened_rows: list[PivotRow] = []

        def flatten(rows: list[PivotRow], parent_id: str = "") -> None:
            for index, row in enumerate(rows):
                row.row_id = f"{parent_id}.{index}" if parent_id else str(index)
                row.parent_id = parent_id
                row.cells = [row.values_by_column.get(path) for path in leaf_column_paths]
                flattened_rows.append(row)
                flatten(row.children, row.row_id)

        flatten(root_rows)

        totals_queryset = self.queryset if self.totals_scope == "dataset" else page_queryset
        column_totals: list[Any] = []
        grand_totals: list[Any] = []
        if self.show_column_totals:
            column_totals = self._column_totals(
                totals_queryset,
                column_paths,
                aggregate_expressions,
            )
            aggregate_totals = totals_queryset.aggregate(**aggregate_expressions)
            grand_totals = [
                aggregate_totals[f"pivot_value_{value_index}"]
                for value_index in range(len(self.value_fields))
            ]

        return PivotTableResult(
            header_rows=self._header_rows(
                column_paths,
                raw_column_paths,
                value_headers,
            ),
            value_headers=value_headers,
            rows=flattened_rows,
            column_totals=column_totals,
            grand_totals=grand_totals,
            effective_aggregations=effective_aggregations,
        )

    def _filter_top_level_rows(self, values: Iterable[Any]) -> QuerySet:
        values = list(values)
        if not values:
            return self.queryset.none()

        field_name = self.row_fields[0].name
        concrete_values = [value for value in values if value is not None]
        query = Q(**{f"{field_name}__in": concrete_values}) if concrete_values else Q()
        if any(value is None for value in values):
            null_query = Q(**{f"{field_name}__isnull": True})
            query = query | null_query if concrete_values else null_query
        return self.queryset.filter(query)

    def _column_paths(self) -> tuple[list[tuple[Any, ...]], dict[tuple[Any, ...], tuple[Any, ...]]]:
        value_count = len(self.value_fields)
        if value_count > MAX_PIVOT_LEAF_COLUMNS:
            raise PivotTableTooWide

        if not self.column_fields:
            return [()], {(): ()}

        names = [item.name for item in self.column_fields]
        max_column_paths = MAX_PIVOT_LEAF_COLUMNS // max(value_count, 1)
        raw_paths = (
            self.queryset.values_list(*names)
            .order_by(*names)
            .distinct()[: max_column_paths + 1]
        )
        paths: list[tuple[Any, ...]] = []
        raw_by_path: dict[tuple[Any, ...], tuple[Any, ...]] = {}
        for index, raw_path in enumerate(raw_paths):
            if index >= max_column_paths:
                raise PivotTableTooWide
            if len(names) == 1:
                raw_path = (raw_path[0],)
            path = tuple(_hashable(value) for value in raw_path)
            if path not in raw_by_path:
                paths.append(path)
                raw_by_path[path] = tuple(raw_path)
        return paths, raw_by_path

    def _column_totals(
        self,
        queryset: QuerySet,
        column_paths: list[tuple[Any, ...]],
        aggregate_expressions: dict[str, Any],
    ) -> list[Any]:
        if not self.column_fields:
            totals = queryset.aggregate(**aggregate_expressions)
            return [
                totals[f"pivot_value_{value_index}"]
                for value_index in range(len(self.value_fields))
            ]

        names = [item.name for item in self.column_fields]
        grouped = (
            queryset.values(*names)
            .annotate(**aggregate_expressions)
            .order_by()
        )
        totals = {
            tuple(_hashable(item[name]) for name in names): [
                item[f"pivot_value_{value_index}"]
                for value_index in range(len(self.value_fields))
            ]
            for item in grouped
        }
        return [
            value
            for path in column_paths
            for value in totals.get(path, [None] * len(self.value_fields))
        ]

    def _header_rows(
        self,
        column_paths: list[tuple[Any, ...]],
        raw_by_path: dict[tuple[Any, ...], tuple[Any, ...]],
        value_headers: list[str],
    ) -> list[list[PivotHeaderCell]]:
        if not self.column_fields:
            return [[PivotHeaderCell(value_header, 1) for value_header in value_headers]]

        rows: list[list[PivotHeaderCell]] = []
        value_count = len(self.value_fields)
        for depth, pivot_field in enumerate(self.column_fields):
            cells: list[PivotHeaderCell] = []
            previous_prefix: tuple[Any, ...] | None = None
            for path in column_paths:
                prefix = path[: depth + 1]
                if prefix == previous_prefix:
                    cells[-1] = PivotHeaderCell(
                        cells[-1].label,
                        cells[-1].colspan + value_count,
                    )
                    continue
                raw_value = raw_by_path[path][depth]
                cells.append(PivotHeaderCell(
                    self._format_dimension_value(pivot_field, raw_value),
                    value_count,
                ))
                previous_prefix = prefix
            rows.append(cells)
        if value_count > 1:
            rows.append([
                PivotHeaderCell(value_header, 1)
                for _column_path in column_paths
                for value_header in value_headers
            ])
        return rows

    @staticmethod
    def _value_header(value_field: PivotValueField, effective_aggregation: str) -> str:
        return f"{value_field.title} ({effective_aggregation.title()})"

    def _effective_aggregation(self, value_field: PivotValueField) -> str:
        aggregation = (
            value_field.aggregation
            if value_field.aggregation in NUMERIC_AGGREGATIONS
            else "count"
        )
        model_field = value_field.model_field
        if isinstance(model_field, models.BooleanField):
            return aggregation if aggregation in BOOLEAN_AGGREGATIONS else "count"
        if isinstance(model_field, NUMERIC_FIELD_TYPES):
            return aggregation
        return "count"

    def _aggregate_expressions(self, effective_aggregations: list[str]) -> dict[str, Any]:
        return {
            f"pivot_value_{value_index}": self._aggregate_expression(
                value_field,
                effective_aggregations[value_index],
            )
            for value_index, value_field in enumerate(self.value_fields)
        }

    @staticmethod
    def _aggregate_expression(value_field: PivotValueField, aggregation: str):
        field_name = value_field.name
        if aggregation == "sum" and isinstance(value_field.model_field, models.BooleanField):
            return Sum(Cast(field_name, output_field=models.IntegerField()))
        return {
            "count": Count(field_name),
            "sum": Sum(field_name),
            "min": Min(field_name),
            "max": Max(field_name),
            "avg": Avg(field_name),
        }[aggregation]

    def _prepare_related_labels(self) -> None:
        """Bulk-load labels for relational dimensions without per-cell queries."""
        for pivot_field in self.row_fields + self.column_fields:
            remote_field = getattr(pivot_field.model_field, "remote_field", None)
            related_model = getattr(remote_field, "model", None)
            if related_model is None:
                continue

            raw_values = list(
                self.queryset.order_by()
                .values_list(pivot_field.name, flat=True)
                .exclude(**{f"{pivot_field.name}__isnull": True})
                .distinct()
            )
            objects = related_model._default_manager.in_bulk(raw_values)
            for object_id, obj in objects.items():
                self._related_labels[(pivot_field.name, _hashable(object_id))] = safe_object_label(obj)

    def _format_dimension_value(self, pivot_field: PivotField, value: Any) -> str:
        if value is None:
            return "Unassigned"
        if isinstance(value, bool):
            return "Yes" if value else "No"

        related_label = self._related_labels.get((pivot_field.name, _hashable(value)))
        if related_label is not None:
            return related_label

        choices = dict(getattr(pivot_field.model_field, "flatchoices", ()) or ())
        if value in choices:
            return str(choices[value])
        if isinstance(value, Decimal):
            return format(value, "f")
        return str(value)


class PivotTableDataviewRenderer(BaseDataviewRenderer):
    """Render permission-filtered records as a reusable pivot table."""

    template_name = "cotton/features/dataviews/pivot_table.html"

    @classmethod
    def paginate_queryset(
        cls,
        queryset: QuerySet,
        preference,
        request: HttpRequest,
        options: object | None = None,
    ) -> DataviewPagination:
        row_field_ids = getattr(options, "row_field_ids", []) or []
        first_row_field = cls._configured_field(
            preference,
            request,
            row_field_ids[0] if row_field_ids else None,
        )
        if first_row_field is None:
            return DataviewPagination(queryset=queryset)

        page_size = int(getattr(options, "page_size", 25))
        top_level_rows = (
            queryset.order_by(first_row_field.field)
            .values_list(first_row_field.field, flat=True)
            .distinct()
        )
        page_obj = cls.paginate_object_list(top_level_rows, page_size, request.GET.get("page", 1))
        return DataviewPagination(
            queryset=queryset,
            page_obj=page_obj,
            pagination_pages=cls.build_pagination_range(page_obj),
            show_global_pagination=True,
        )

    def get_context_data(self, pagination: DataviewPagination) -> dict[str, Any]:
        context = super().get_context_data(pagination)
        row_fields = self._resolve_fields(getattr(self.options, "row_field_ids", []))
        column_fields = self._resolve_fields(getattr(self.options, "column_field_ids", []))
        resolved_value_fields = self._resolve_fields(
            getattr(self.options, "value_field_ids", [])
        )
        aggregation = getattr(self.options, "aggregation", "count")
        value_fields = [
            PivotValueField(
                name=value_field.name,
                title=value_field.title,
                model_field=value_field.model_field,
                aggregation=aggregation,
            )
            for value_field in resolved_value_fields
        ]

        context.update({
            "pivot_configured": bool(row_fields and value_fields),
            "pivot_result": None,
            "pivot_too_wide": False,
            "pivot_show_row_totals": bool(getattr(self.options, "show_row_totals", True)),
            "pivot_show_column_totals": bool(getattr(self.options, "show_column_totals", True)),
        })
        if not row_fields or not value_fields or pagination.page_obj is None:
            return context

        pivot_table = PivotTable(
            queryset=self.state.queryset,
            row_fields=row_fields,
            column_fields=column_fields,
            value_fields=value_fields,
            show_row_totals=getattr(self.options, "show_row_totals", True),
            show_column_totals=getattr(self.options, "show_column_totals", True),
            totals_scope=getattr(self.options, "totals_scope", "page"),
        )
        try:
            context["pivot_result"] = pivot_table.build(pagination.page_obj.object_list)
        except PivotTableTooWide:
            context["pivot_too_wide"] = True
        return context

    def _resolve_fields(self, field_ids: Iterable[Any]) -> list[PivotField]:
        fields: list[PivotField] = []
        seen: set[int] = set()
        for field_id in field_ids or []:
            application_field = self.get_field_from_data_view_fields(self.state.fields, field_id)
            if application_field is None or application_field.id in seen:
                continue
            try:
                model_field = self.state.model._meta.get_field(application_field.field)
            except FieldDoesNotExist:
                continue
            seen.add(application_field.id)
            fields.append(PivotField(
                name=application_field.field,
                title=application_field.title,
                model_field=model_field,
            ))
        return fields

    @staticmethod
    def _configured_field(preference, request: HttpRequest, field_id: Any) -> ApplicationField | None:
        if field_id in (None, ""):
            return None
        try:
            application_field = preference.content_type.applicationfield_set.get(pk=int(field_id))
            preference.content_type.model_class()._meta.get_field(application_field.field)
        except (TypeError, ValueError, ApplicationField.DoesNotExist, FieldDoesNotExist):
            return None

        if not UserPolicyManager(request.user).has_field_permission(application_field, BloomerpPermission.VIEW):
            return None
        return application_field
