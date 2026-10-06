"""Migration-safe JSON field enforcing versioned Pydantic storage schemas."""

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.db.backends.base.base import BaseDatabaseWrapper
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from bloomerp.agents.definition import PAYLOAD_SCHEMAS


class AgentJSONField(models.JSONField):
    """Validate both model cleaning and ordinary ORM literal JSON writes."""

    def __init__(self, *args: Any, schema: str = "object.v1", **kwargs: Any) -> None:
        """Select an import-stable versioned schema for this persisted field."""
        if schema not in PAYLOAD_SCHEMAS:
            raise ValueError(f"Unknown agent payload schema: {schema}")
        self.schema = schema
        super().__init__(*args, **kwargs)

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        """Preserve the schema identifier in generated migrations."""
        name, path, args, kwargs = super().deconstruct()
        kwargs["schema"] = self.schema
        return name, path, args, kwargs

    def normalize(self, value: Any) -> Any:
        """Validate and convert model instances into plain JSON-compatible values."""
        if value is None and self.null:
            return None
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        try:
            validated = PAYLOAD_SCHEMAS[self.schema].model_validate(value)
            result = validated.model_dump(mode="json")
            # The JSON encoder rejects NaN even inside adapter-owned objects.
            import json

            json.dumps(result, allow_nan=False)
            return result
        except (PydanticValidationError, ValueError, TypeError) as exc:
            raise ValidationError(
                "Invalid agent payload for %(schema)s: %(error)s",
                params={"schema": self.schema, "error": str(exc)},
            ) from exc

    def clean(self, value: Any, model_instance: models.Model) -> Any:
        """Run schema validation even for empty dictionaries and lists."""
        return super().clean(self.normalize(value), model_instance)

    def get_db_prep_value(
        self, value: Any, connection: BaseDatabaseWrapper, prepared: bool = False
    ) -> Any:
        """Reject invalid literal payloads before serializing a database write."""
        return super().get_db_prep_value(self.normalize(value), connection, prepared)
