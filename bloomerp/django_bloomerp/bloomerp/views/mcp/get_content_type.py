"""Resolve Django model labels to content-type identities through MCP."""

from typing import Any

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest
from rest_framework import serializers
from rest_framework.response import Response

from bloomerp.mcp.definition import McpTool
from bloomerp.router import router


class ContentTypeRequestSerializer(serializers.Serializer):
    """Validate the model identity supplied to the content-type tool."""

    model_label = serializers.RegexField(
        regex=r"^[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*$",
    )


@router.register(
    name="Get content type",
    url_name="get_content_type",
    route_type="mcp",
    description="Resolve a Django model label, such as sales.Customer, to its content type.",
    mcp=McpTool(
        title="Get content type",
        input_schema={
            "type": "object",
            "properties": {
                "model_label": {
                    "type": "string",
                    "pattern": r"^[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*$",
                    "description": "Django model label from an artifact or mutation catalog.",
                },
            },
            "required": ["model_label"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "app_label": {"type": "string"},
                "model": {"type": "string"},
            },
            "required": ["id", "app_label", "model"],
            "additionalProperties": False,
        },
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def get_content_type(request: HttpRequest) -> dict[str, Any] | Response:
    """Return an installed model's existing content type using a case-insensitive label."""
    if not request.user.is_authenticated:
        return Response({"detail": "Authentication required"}, status=401)
    serializer = ContentTypeRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)
    model_label = serializer.validated_data["model_label"]
    try:
        model = apps.get_model(model_label.lower())
    except (LookupError, ValueError):
        return Response({"model_label": "Unknown model label."}, status=400)
    try:
        content_type = ContentType.objects.get_by_natural_key(
            model._meta.app_label, model._meta.model_name
        )
    except ContentType.DoesNotExist:
        return Response({"model_label": "Content type not found."}, status=404)
    return {
        "id": content_type.pk,
        "app_label": content_type.app_label,
        "model": content_type.model,
    }
