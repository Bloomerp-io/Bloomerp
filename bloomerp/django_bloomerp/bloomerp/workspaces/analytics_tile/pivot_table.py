"""SQL-backed analytics pivots using the dataview's table and interaction contract."""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db import connection
from django.http import HttpRequest
from django.utils.translation import gettext as _

from bloomerp.dataviews.pivot_table.renderer import (
    MAX_PIVOT_LEAF_COLUMNS,
    PivotHeaderCell,
    PivotRow,
    PivotTableResult,
    PivotTableTooWide,
    _hashable,
)
from bloomerp.services.sql_services import SqlExecutor, SqlQueryResponse
from bloomerp.workspaces.analytics_tile.sql_utils import quote_identifier, strip_trailing_query_semicolon
from bloomerp.workspaces.analytics_tile.table import get_renderer_url
from bloomerp.workspaces.analytics_tile.utils import TileFieldType, to_primitive_field_type
from bloomerp.workspaces.base import BaseTileRenderer

if TYPE_CHECKING:
    from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig, FieldConfig


MAX_PIVOT_RENDERED_ROWS = 1000


class PivotTableTooTall(Exception):
    """Raised before a nested pivot page can exceed its bounded rendering budget."""


def pivot_aggregator_choices(field_type: TileFieldType | None) -> list[tuple[str, str]]:
    """Offer the same type-specific aggregations as the pivot dataview."""
    choices = [("count", _("Count"))]
    if field_type in (TileFieldType.NUMERIC, TileFieldType.BOOL):
        choices.append(("sum", _("Sum")))
    if field_type == TileFieldType.NUMERIC:
        choices.extend([("min", _("Minimum")), ("max", _("Maximum")), ("avg", _("Average"))])
    return choices


def dimension_label(value: Any) -> str:
    """Display SQL dimensions with the dataview's null and boolean conventions."""
    if value is None:
        return _("Unassigned")
    if isinstance(value, bool):
        return _("Yes") if value else _("No")
    return format(value, "f") if isinstance(value, Decimal) else str(value)


def field_label(field: FieldConfig) -> str:
    """Use an optional configured title while retaining the exact SQL identifier."""
    return (field.opts or {}).get("label") or field.name


class AnalyticsPivotTable:
    """Format bounded SQL aggregates into the shared dataview presentation contract."""

    def __init__(self, config: AnalyticsTileConfig, query: str, executor: SqlExecutor) -> None:
        """Store the framework-filtered query and selected dimension/value slots."""
        self.rows = config.fields.get("rows") or []
        self.columns = config.fields.get("columns") or []
        self.values = config.fields.get("values") or []
        self.source = f"WITH bloomerp_pivot_source AS ({strip_trailing_query_semicolon(query)})"
        self.executor = executor
        self.page_predicate = ""
        self.aggregations: list[str] = []
        self.expressions: list[str] = []
        self.value_aliases: list[str] = []
        self.output_names: set[str] = set()

    def prepare(self, page: int, page_size: int) -> SqlQueryResponse:
        """Validate output fields, enforce column limits, and paginate root groups."""
        if len(self.values) > MAX_PIVOT_LEAF_COLUMNS:
            raise PivotTableTooWide
        sample = self.executor.execute_query(
            f"{self.source} SELECT * FROM bloomerp_pivot_source LIMIT 1", paginate=False,
        )
        types = {
            item.name: to_primitive_field_type(item.field_type)
            for item in sample.output_fields.fields
        } if sample.output_fields else {}
        for field in self.rows + self.columns + self.values:
            if field.name not in sample.columns:
                raise ValueError(_("A selected pivot field is no longer returned by the query."))
        self.output_names = set(sample.columns)
        for index, field in enumerate(self.values):
            primitive = types.get(field.name, TileFieldType.TEXT)
            if primitive == TileFieldType.TEXT and sample.rows and sample.rows[0].get(field.name) is None:
                # SQLite reports no cursor types; inspect a non-null value just as
                # the framework SQL preview does when inferring primitive types.
                name = quote_identifier(field.name)
                probe = self.executor.execute_query(
                    f"{self.source} SELECT {name} FROM bloomerp_pivot_source WHERE {name} IS NOT NULL LIMIT 1",
                    paginate=False,
                )
                if probe.output_fields and probe.output_fields.fields:
                    primitive = to_primitive_field_type(probe.output_fields.fields[0].field_type)
            requested = str((field.opts or {}).get("aggregator") or "count").lower()
            allowed = dict(pivot_aggregator_choices(primitive))
            aggregation = requested if requested in allowed else "count"
            self.aggregations.append(aggregation)
            column = f"pivot_source.{quote_identifier(field.name)}"
            if aggregation == "sum" and primitive == TileFieldType.BOOL:
                column = f"CASE WHEN {column} THEN 1 WHEN {column} IS NULL THEN NULL ELSE 0 END"
            alias = self.output_alias(f"pivot_value_{index}")
            self.value_aliases.append(alias)
            self.expressions.append(f"{aggregation.upper()}({column}) AS {quote_identifier(alias)}")
        root = quote_identifier(self.rows[0].name)
        root_query = f"SELECT {root} FROM bloomerp_pivot_source GROUP BY {root} ORDER BY {root}"
        result = self.executor.execute_query(f"{self.source} {root_query}", page=page, page_size=page_size)
        # Reuse the already fetched page keys instead of rediscovering the page
        # inside every hierarchy and totals query. The existing literal compiler
        # escapes values for the active backend; identifiers remain quoted separately.
        from bloomerp.workspaces.analytics_tile.model import _lookup_sql_literal

        page_values = [record[self.rows[0].name] for record in result.rows]
        literals = [
            _lookup_sql_literal(value, dialect=connection.vendor)
            for value in page_values if value is not None
        ]
        predicates = [f"pivot_source.{root} IN ({', '.join(literals)})"] if literals else []
        if None in page_values:
            predicates.append(f"pivot_source.{root} IS NULL")
        self.page_predicate = " WHERE (" + " OR ".join(predicates or ["1 = 0"]) + ")"
        return result

    def output_alias(self, preferred: str) -> str:
        """Reserve a generated column alias that cannot overwrite a query output field."""
        alias = preferred
        while alias in self.output_names:
            alias = f"_{alias}"
        self.output_names.add(alias)
        return alias

    def grouped_rows(self, fields: list[FieldConfig], limit: int) -> list[dict[str, Any]]:
        """Fetch bounded SQL aggregates, using one extra record to detect overflow."""
        names = list(dict.fromkeys(f"pivot_source.{quote_identifier(field.name)}" for field in fields))
        selections = [*names, *self.expressions]
        grouping = f" GROUP BY {', '.join(names)} ORDER BY {', '.join(names)}" if names else ""
        query = (
            f"{self.source} SELECT {', '.join(selections)} "
            f"FROM bloomerp_pivot_source AS pivot_source"
            f"{self.page_predicate}{grouping} LIMIT {limit + 1 if fields else 1}"
        )
        records = self.executor.execute_query(query, paginate=False).rows
        if len(records) > limit:
            raise PivotTableTooTall
        return records

    def column_key(self, record: dict[str, Any]) -> tuple[Any, ...]:
        """Identify a grouped column using the dataview's hashable dimension convention."""
        return tuple(_hashable(record[field.name]) for field in self.columns)

    def cells(self, values: dict[tuple[Any, ...], list[Any]], paths: list[tuple[Any, ...]]) -> list[Any]:
        """Arrange database aggregates into bounded cells without recalculating measures."""
        return [
            value
            for path in paths
            for value in values.get(tuple(_hashable(item) for item in path), [None] * len(self.values))
        ]

    def column_paths(self) -> list[tuple[Any, ...]]:
        """Bound column discovery before constructing the same maximum-width pivot as dataviews."""
        if not self.columns:
            return [()]
        names = ", ".join(dict.fromkeys(quote_identifier(field.name) for field in self.columns))
        limit = MAX_PIVOT_LEAF_COLUMNS // len(self.values)
        query = (
            f"{self.source} SELECT {names} FROM bloomerp_pivot_source "
            f"GROUP BY {names} ORDER BY {names} LIMIT {limit + 1}"
        )
        rows = self.executor.execute_query(query, paginate=False).rows
        if len(rows) > limit:
            raise PivotTableTooWide
        return [tuple(row[field.name] for field in self.columns) for row in rows]

    def value_list(self, record: dict[str, Any]) -> list[Any]:
        """Read aggregation aliases in the configured measure order."""
        return [record.get(alias) for alias in self.value_aliases]

    def headers(self, paths: list[tuple[Any, ...]], titles: list[str]) -> list[list[PivotHeaderCell]]:
        """Build the nested header contract consumed by the shared pivot template."""
        if not self.columns:
            return [[PivotHeaderCell(title, 1) for title in titles]]
        headers: list[list[PivotHeaderCell]] = []
        for depth in range(len(self.columns)):
            cells: list[PivotHeaderCell] = []
            previous: tuple[Any, ...] | None = None
            for path in paths:
                prefix = tuple(_hashable(item) for item in path[:depth + 1])
                if prefix == previous:
                    last = cells[-1]
                    cells[-1] = PivotHeaderCell(last.label, last.colspan + len(self.values))
                else:
                    cells.append(PivotHeaderCell(dimension_label(path[depth]), len(self.values)))
                previous = prefix
            headers.append(cells)
        if len(self.values) > 1:
            headers.append([PivotHeaderCell(title, 1) for _path in paths for title in titles])
        return headers

    def build(self) -> PivotTableResult:
        """Arrange bounded database aggregates into cells, headers, and expandable rows."""
        raw_columns = self.column_paths()
        titles = [
            f"{field_label(field)} ({dict(pivot_aggregator_choices(TileFieldType.NUMERIC))[aggregation]})"
            for field, aggregation in zip(self.values, self.aggregations)
        ]
        nodes: dict[tuple[Any, ...], PivotRow] = {}
        roots: list[PivotRow] = []
        for depth in range(len(self.rows)):
            fields = self.rows[:depth + 1]
            records = self.grouped_rows(fields, MAX_PIVOT_RENDERED_ROWS - len(nodes))
            for record in records:
                raw_path = tuple(record[field.name] for field in fields)
                path = tuple(_hashable(value) for value in raw_path)
                node = PivotRow(
                    path=path, raw_path=raw_path, label=dimension_label(raw_path[-1]), depth=depth,
                    totals=self.value_list(record),
                )
                nodes[path] = node
                if depth:
                    nodes[path[:-1]].children.append(node)
                else:
                    roots.append(node)

            if self.columns and records:
                # At most one aggregate record per rendered row and column path.
                # Across all depths this is bounded by the row and leaf-column caps.
                grouped = self.grouped_rows(fields + self.columns, len(records) * len(raw_columns))
                for record in grouped:
                    path = tuple(_hashable(record[field.name]) for field in fields)
                    nodes[path].values_by_column[self.column_key(record)] = self.value_list(record)
            for record in records:
                path = tuple(_hashable(record[field.name]) for field in fields)
                node = nodes[path]
                node.cells = self.cells(node.values_by_column, raw_columns) if self.columns else node.totals

        flattened: list[PivotRow] = []
        pending = [(row, "", index) for index, row in reversed(list(enumerate(roots)))]
        while pending:
            row, parent_id, index = pending.pop()
            row.row_id = f"{parent_id}.{index}" if parent_id else str(index)
            row.parent_id = parent_id
            flattened.append(row)
            pending.extend(
                (child, row.row_id, child_index)
                for child_index, child in reversed(list(enumerate(row.children)))
            )

        totals = self.grouped_rows([], 1)[0]
        column_values = {
            self.column_key(record): self.value_list(record)
            for record in self.grouped_rows(self.columns, len(raw_columns))
        } if self.columns and raw_columns else {}
        return PivotTableResult(
            header_rows=self.headers(raw_columns, titles), value_headers=titles, rows=flattened,
            column_totals=self.cells(column_values, raw_columns) if self.columns else self.value_list(totals),
            grand_totals=self.value_list(totals), effective_aggregations=self.aggregations,
        )


class AnalyticsPivotTableRenderer(BaseTileRenderer):
    """Render analytics SQL through the framework and reuse the pivot dataview frontend."""

    template_name = "cotton/features/workspaces/tiles/pivot_table.html"

    @classmethod
    def render(cls, config: AnalyticsTileConfig, request: HttpRequest) -> str:
        """Render complete pivots, safe width feedback, or an incomplete editor draft."""
        from bloomerp.workspaces.analytics_tile.model import get_filtered_query

        context: dict[str, Any] = {
            "pivot_configured": bool(config.fields.get("rows") and config.fields.get("values")),
            "pivot_show_row_totals": True, "pivot_show_column_totals": True,
        }
        if not context["pivot_configured"]:
            return cls.render_to_string(context)
        try:
            page = max(1, int(request.GET.get("page", 1)))
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = int((config.opts or {}).get("page_size", 25))
        except (TypeError, ValueError):
            page_size = 25
        if page_size not in (10, 25, 50, 100):
            page_size = 25
        pivot = AnalyticsPivotTable(
            config, get_filtered_query(config, request.GET, request=request), SqlExecutor(request.user),
        )
        try:
            pagination = pivot.prepare(page, page_size)
            context["pivot_result"] = pivot.build()
        except PivotTableTooWide:
            context["pivot_too_wide"] = True
            return cls.render_to_string(context)
        except PivotTableTooTall:
            context["pivot_too_tall"] = True
            return cls.render_to_string(context)
        params = request.GET.copy()
        params.pop("page", None)
        context.update({
            "show_global_pagination": pagination.total_pages > 1,
            "current_page": pagination.page, "total_pages": pagination.total_pages,
            "has_previous": pagination.page > 1, "has_next": pagination.page < pagination.total_pages,
            "previous_page_number": pagination.page - 1, "next_page_number": pagination.page + 1,
            "pagination_url": get_renderer_url(), "pagination_querystring": params.urlencode(),
        })
        return cls.render_to_string(context)
