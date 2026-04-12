from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd


from bloomerp.workspaces.analytics_tile.utils import Aggregator, Formatter
from bloomerp.workspaces.base import BaseTileRenderer

if TYPE_CHECKING:
	from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig
	from bloomerp.workspaces.analytics_tile.model import FieldConfig


def _render_value(field: FieldConfig, data: pd.DataFrame) -> str:
	"""
	Applies a:
		- aggregator (based on the data)
		- formatter
		- prefix/suffix
	"""
	if field.name not in data.columns:
		return ""

	field_opts = field.opts or {}
	series = data[field.name]
	aggregator_name = field_opts.get("aggregator") or "FIRST"
	aggregator = Aggregator[aggregator_name]
	value = aggregator.value.func(series)

	formatter_name = field_opts.get("formatter")
	if formatter_name:
		value = Formatter[formatter_name].value.func(value)

	if value is None:
		value = ""

	prefix = field_opts.get("prefix") or ""
	suffix = field_opts.get("suffix") or ""

	return f"{prefix}{value}{suffix}"


class AnalyticsKpiRenderer(BaseTileRenderer):
	template_name = "cotton/workspaces/tiles/kpi.html"

	@classmethod
	def render(cls, config: AnalyticsTileConfig, user, data):
		value = ""
		sub_value = ""

		for field in config.fields.get("value") or []:
			value += str(_render_value(field, data))
		
		for field in config.fields.get("sub_value") or []:
			sub_value += str(_render_value(field, data))

		return cls.render_to_string({
			"value": value,
			"sub_value": sub_value,
		})
