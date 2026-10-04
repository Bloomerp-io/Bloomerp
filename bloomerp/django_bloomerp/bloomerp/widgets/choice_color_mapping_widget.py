"""Mapping rows that retain only the choice keys still available for coloring."""

from __future__ import annotations

import json
from typing import Any

from bloomerp.widgets.mapping_widget import MappingWidget


class ChoiceColorMappingWidget(MappingWidget):
    """Let users add and remove color mappings without rendering retired keys."""

    def get_context(
        self, name: str, value: Any, attrs: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Filter old mappings while preserving the reusable mapping row editor."""
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                value = None
        known = {str(key) for key, _label in self.left or []}
        if isinstance(value, dict):
            value = {key: color for key, color in value.items() if str(key) in known}
        elif isinstance(value, (list, tuple)):
            value = [
                row
                for row in value
                if isinstance(row, (list, tuple))
                and len(row) == 2
                and str(row[0]) in known
            ]
        return super().get_context(name, value, attrs)
