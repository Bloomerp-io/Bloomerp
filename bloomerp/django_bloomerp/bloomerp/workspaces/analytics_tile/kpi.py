from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd
from django.template import engines


from bloomerp.services.sql_services import SqlExecutor
from bloomerp.workspaces.analytics_tile.sql_utils import quote_identifier, strip_trailing_query_semicolon
from bloomerp.workspaces.analytics_tile.utils import Aggregator, Formatter
from bloomerp.workspaces.base import BaseTileRenderer

if TYPE_CHECKING:
    from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig
    from bloomerp.workspaces.analytics_tile.model import FieldConfig


@dataclass(frozen=True)
class KpiAggregatedField:
    field: FieldConfig
    alias: str


def _normalize_value(value):
    if pd.isna(value):
        return None
    return value


def _sql_expression_for_aggregator(field_name: str, aggregator_name: str) -> tuple[str, bool]:
    column = quote_identifier(field_name)
    numbered_source = "bloomerp_kpi_numbered"

    if aggregator_name == "FIRST":
        return f"(SELECT {column} FROM {numbered_source} ORDER BY bloomerp_kpi_row_number ASC LIMIT 1)", True

    if aggregator_name == "LAST":
        return f"(SELECT {column} FROM {numbered_source} ORDER BY bloomerp_kpi_row_number DESC LIMIT 1)", True

    if aggregator_name == "SUM":
        return f"SUM({column})", False

    if aggregator_name == "AVG":
        return f"AVG({column})", False

    if aggregator_name == "COUNT":
        return f"COUNT({column})", False

    raise ValueError(f"Unsupported KPI aggregator: {aggregator_name}")


def build_kpi_aggregation_query(query: str, fields: list[FieldConfig]) -> tuple[str, list[KpiAggregatedField]]:
    """Builds a single-row SQL query with KPI aggregations applied before execution."""

    base_query = strip_trailing_query_semicolon(query)
    aggregated_fields: list[KpiAggregatedField] = []
    select_expressions: list[str] = []
    needs_numbered_source = False
    needs_aggregate_source = False

    for index, field in enumerate(fields):
        field_opts = field.opts or {}
        aggregator_name = field_opts.get("aggregator") or "FIRST"
        Aggregator[aggregator_name]

        alias = f"bloomerp_kpi_value_{index}"
        expression, uses_numbered_source = _sql_expression_for_aggregator(field.name, aggregator_name)
        needs_numbered_source = needs_numbered_source or uses_numbered_source
        needs_aggregate_source = needs_aggregate_source or not uses_numbered_source
        select_expressions.append(f"{expression} AS {quote_identifier(alias)}")
        aggregated_fields.append(KpiAggregatedField(field=field, alias=alias))

    if not select_expressions:
        return "SELECT NULL AS bloomerp_kpi_empty_value", []

    ctes = [
        "bloomerp_kpi_source AS (\n"
        f"{base_query}\n"
        ")"
    ]
    if needs_numbered_source:
        ctes.append(
            "bloomerp_kpi_numbered AS (\n"
            "SELECT bloomerp_kpi_source.*, ROW_NUMBER() OVER () AS bloomerp_kpi_row_number "
            "FROM bloomerp_kpi_source\n"
            ")"
        )

    from_clause = " FROM bloomerp_kpi_source" if needs_aggregate_source else ""
    return (
        f"WITH {', '.join(ctes)}\n"
        f"SELECT {', '.join(select_expressions)}{from_clause}",
        aggregated_fields,
    )


def _render_value(field: FieldConfig, data: pd.DataFrame, column_name: str | None = None) -> str:
    """
    Applies a:
        - aggregator (based on the data)
        - formatter
        - prefix/suffix
    """
    data_column = column_name or field.name
    if data_column not in data.columns:
        return ""

    field_opts = field.opts or {}
    series = data[data_column]
    if column_name is None:
        aggregator_name = field_opts.get("aggregator") or "FIRST"
        aggregator = Aggregator[aggregator_name]
        value = aggregator.value.func(series)
    else:
        value = series.iloc[0] if len(series) > 0 else None

    value = _normalize_value(value)

    formatter_name = field_opts.get("formatter")
    if formatter_name and formatter_name != "NONE":
        value = Formatter[formatter_name].value.func(value)

    if value is None:
        value = ""

    prefix = field_opts.get("prefix") or ""
    suffix = field_opts.get("suffix") or ""

    return f"{prefix}{value}{suffix}"


def _build_section_vars(aggregated_fields: list[KpiAggregatedField], data: pd.DataFrame) -> dict[str, object]:
    vars: dict[str, object] = {}

    for aggregated_field in aggregated_fields:
        data_column = aggregated_field.alias
        if data_column not in data.columns:
            continue

        field_name = aggregated_field.field.name.lower().replace(" ", "_")
        series = data[data_column]
        preformatted_value = series.iloc[0] if len(series) > 0 else None
        vars[f"preformatted_var_{field_name}"] = _normalize_value(preformatted_value)
        vars[f"var_{field_name}"] = _render_value(aggregated_field.field, data, data_column)

    return vars


def _render_section(
    aggregated_fields: list[KpiAggregatedField],
    data: pd.DataFrame,
    advanced_formatting: str | None = None,
) -> str:
    vars = _build_section_vars(aggregated_fields, data)
    value = "".join(
        str(_render_value(aggregated_field.field, data, aggregated_field.alias))
        for aggregated_field in aggregated_fields
    )

    if advanced_formatting and advanced_formatting.strip():
        vars["value"] = value
        value = engines["django"].from_string(advanced_formatting).render(vars)

    return value


class AnalyticsKpiRenderer(BaseTileRenderer):
    template_name = "cotton/workspaces/tiles/kpi.html"

    @classmethod
    def render(cls, config: AnalyticsTileConfig, request):
        from bloomerp.workspaces.analytics_tile.model import get_filtered_query
        
        query = get_filtered_query(config, request.GET)
        value_fields = config.fields.get("value") or []
        sub_value_fields = config.fields.get("sub_value") or []
        kpi_query, aggregated_fields = build_kpi_aggregation_query(
            query,
            [*value_fields, *sub_value_fields],
        )
        data = SqlExecutor(request.user).execute_query(kpi_query, paginate=False).to_dataframe()

        value_aliases = aggregated_fields[:len(value_fields)]
        sub_value_aliases = aggregated_fields[len(value_fields):]

        value = _render_section(
            value_aliases,
            data,
            config.opts.get("advanced_formatting_value"),
        )
        sub_value = _render_section(
            sub_value_aliases,
            data,
            config.opts.get("advanced_formatting_sub_value"),
        )
        
        return cls.render_to_string({
            "value": value,
            "sub_value": sub_value,
        })
