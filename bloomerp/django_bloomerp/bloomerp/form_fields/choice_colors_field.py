"""Color mappings restricted to the choices that still exist on a field."""

from __future__ import annotations

import json
from typing import Any

from bloomerp.form_fields.mapping_field import MappingField


class ChoiceColorsField(MappingField):
    """Ignore retired choice keys while validating colors for current choices."""

    def to_python(self, value: Any) -> dict[str, Any]:
        """Drop stale keys from saved or submitted mappings before validation."""
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                return super().to_python(value)
        if isinstance(value, dict):
            value = list(value.items())
        if isinstance(value, (list, tuple)):
            known = {str(key) for key, _label in self.left or []}
            value = [
                row
                for row in value
                if not isinstance(row, (list, tuple))
                or len(row) != 2
                or str(row[0]) in known
            ]
        return super().to_python(value)
