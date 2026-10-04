"""Private conversation API contracts shared by generated HTTP and MCP adapters."""

from collections.abc import Mapping
from functools import partial
from typing import Any
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import QuerySet
from pydantic import ValidationError as PayloadValidationError
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request

from bloomerp.agents.controller import AgentChatRequest, AgentController
from bloomerp.models.agents import AIConversation, AIMessage


def filter_agent_api_queryset(request: Request, queryset: QuerySet) -> QuerySet:
    """Prevent private relation filters from becoming a credential/checkpoint oracle."""
    from bloomerp.filters.manager import ModelFilterManager
    from bloomerp.filters.parser import parse_filters

    readable = set(agent_api_serializer(queryset.model._meta.label_lower).Meta.fields)
    readable.add("pk")
    readable.update(
        {"selected_agent__pk"}
        if queryset.model is AIConversation
        else {"conversation__pk", "run__pk"}
    )
    try:
        filters = parse_filters(request.query_params, model=queryset.model)
        if any(
            condition.field_path not in readable
            for group in filters
            for condition in group.conditions
        ):
            raise PermissionDenied(
                "Filtering private agent relations is not permitted."
            )
        return ModelFilterManager(queryset.model).apply(filters, queryset=queryset)
    except DjangoValidationError as error:
        raise serializers.ValidationError({"filter": error.messages}) from error


def scope_agent_api_queryset(
    queryset: QuerySet, user: Any, action: str | None
) -> QuerySet:
    """Enforce owner-only transcript reads even with broader administrator policies."""
    if (
        action not in {None, "list", "retrieve", "read"}
        or not user.is_authenticated
        or not get_user_model().objects.filter(pk=user.pk, is_active=True).exists()
    ):
        return queryset.none()
    if queryset.model is AIConversation:
        return queryset.filter(owner_id=user.pk)
    return queryset.filter(
        conversation__owner_id=user.pk, role__in=["user", "assistant"]
    )


class PrivateAgentSerializer(serializers.ModelSerializer):
    """Reject unknown and server-managed input instead of silently ignoring it."""

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Allow only explicit writable fields and require a current server actor."""
        self.controller()
        if not isinstance(data, Mapping):
            raise serializers.ValidationError("Expected an object.")
        writable = {name for name, field in self.fields.items() if not field.read_only}
        denied = set(data) - writable
        if denied:
            raise serializers.ValidationError(
                {name: "This field cannot be supplied." for name in sorted(denied)}
            )
        return super().to_internal_value(data)

    def controller(self) -> AgentController:
        """Bind identity to the authenticated request, never to submitted fields."""
        request = self.context.get("request")
        if request is None:
            raise PermissionDenied("An authenticated request is required.")
        controller = AgentController(request.user)
        try:
            controller.authorize()
        except DjangoPermissionDenied as error:
            raise PermissionDenied("Agent access denied.") from error
        return controller

    def to_representation(self, instance: AIConversation | AIMessage) -> dict[str, Any]:
        """Honor field grants and nested projections just like generated serializers."""
        from bloomerp.utils.api import ApiAccessResolver

        data = super().to_representation(instance)
        request = self.context.get("request")
        if request is not None:
            action = getattr(self.context.get("view"), "action", None) or "retrieve"
            allowed = ApiAccessResolver(request).get_accessible_field_names(
                type(instance), action
            )
            if allowed is not None:
                data = {key: value for key, value in data.items() if key in allowed}
        requested = self.context.get("bloomerp_nested_fields")
        if requested is not None:
            selected = set(requested)
            if self.context.get("bloomerp_auto_pk", True):
                selected.add(instance._meta.pk.name)
            data = {key: value for key, value in data.items() if key in selected}
        return data


class AIConversationSerializer(PrivateAgentSerializer):
    """Create an owned conversation while retaining separate agent-use authorization."""

    class Meta:
        model = AIConversation
        fields = (
            "id",
            "title",
            "selected_agent",
            "status",
            "datetime_created",
            "datetime_updated",
        )
        read_only_fields = ("id", "status", "datetime_created", "datetime_updated")

    def get_fields(self) -> dict[str, serializers.Field]:
        """Limit relation validation and browsable choices to usable agent metadata."""
        from bloomerp.agents.access import AIAgentAccessManager
        from bloomerp.models.agents import AIAgent

        fields = super().get_fields()
        request = self.context.get("request")
        fields["selected_agent"].queryset = (
            AIAgentAccessManager(request.user)
            .get_accessible_queryset()
            .filter(enabled=True)
            .exclude(credentials_encrypted={})
            if request is not None
            else AIAgent.objects.none()
        )
        return fields

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Pin a currently permitted agent and assign ownership on the server."""
        controller = self.controller()
        selected = attrs.get("selected_agent")
        try:
            attrs["selected_agent"] = controller.select_agent(
                selected.pk if selected else None
            )
        except DjangoPermissionDenied as error:
            raise PermissionDenied(str(error)) from error
        attrs["owner"] = controller.user
        return attrs

    def create(self, validated_data: dict[str, Any]) -> AIConversation:
        """Recheck live grants before persisting server-owned conversation metadata."""
        validated_data = self.validate(validated_data)
        actor = self.controller().user
        return AIConversation.objects.create(
            **validated_data, created_by=actor, updated_by=actor
        )


class AIMessageSerializer(PrivateAgentSerializer):
    """Accept plain user text through the same durable controller used by sockets."""

    id = serializers.UUIDField(required=False)
    content_blocks = serializers.JSONField()

    class Meta:
        model = AIMessage
        fields = (
            "id",
            "conversation",
            "content_blocks",
            "sequence",
            "role",
            "status",
            "run",
            "datetime_created",
        )
        read_only_fields = ("sequence", "role", "status", "run", "datetime_created")
        validators = ()

    def get_fields(self) -> dict[str, serializers.Field]:
        """Limit relation resolution to the current actor's own conversations."""
        fields = super().get_fields()
        request = self.context.get("request")
        fields["conversation"].queryset = (
            scope_agent_api_queryset(AIConversation.objects.all(), request.user, "read")
            if request is not None
            else AIConversation.objects.none()
        )
        return fields

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Validate the controller payload without accepting roles or run state."""
        controller = self.controller()
        conversation = attrs["conversation"]
        try:
            controller.load_conversation(conversation.pk)
            controller.select_agent(conversation.selected_agent_id)
            payload = AgentChatRequest(
                conversation_id=conversation.pk,
                content=attrs["content_blocks"],
                client_message_id=attrs.get("id"),
            )
        except DjangoPermissionDenied as error:
            raise PermissionDenied(str(error)) from error
        except PayloadValidationError as error:
            raise serializers.ValidationError(
                {"content_blocks": "Invalid message content."}
            ) from error
        attrs["content_blocks"] = payload.content.model_dump(mode="json")
        return attrs

    def create(self, validated_data: dict[str, Any]) -> AIMessage:
        """Create a user message and run atomically, dispatching only after commit."""
        controller = self.controller()
        controller.instance_settings()
        try:
            submission = controller.accept_message(
                AgentChatRequest(
                    conversation_id=validated_data["conversation"].pk,
                    content=validated_data["content_blocks"],
                    client_message_id=validated_data.get("id") or uuid4(),
                )
            )
        except DjangoPermissionDenied as error:
            raise PermissionDenied(str(error)) from error
        except DjangoValidationError as error:
            raise serializers.ValidationError(
                {"content_blocks": error.messages}
            ) from error
        transaction.on_commit(partial(controller.dispatch_sync, submission.run_id))
        return AIMessage.objects.get(pk=submission.message_id)


def agent_api_serializer(model_label: str) -> type[serializers.ModelSerializer]:
    """Select the fixed, safe serializer for the two exposed transcript models."""
    return {
        "bloomerp.aiconversation": AIConversationSerializer,
        "bloomerp.aimessage": AIMessageSerializer,
    }[model_label]
