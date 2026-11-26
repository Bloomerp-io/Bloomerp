"""Read and update the page trigger for a tutorial draft."""

from uuid import UUID

from django.db import transaction
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext as _
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from bloomerp.models.tutorial import TutorialRevision
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import RouteType, router
from bloomerp.sdk.definition import SdkEndpoint
from bloomerp.serializers.tutorial_step import (
    resolve_step_page,
    validate_local_step_path,
)
from bloomerp.views.api.base import BaseBloomerpApiView


class RevisionTriggerSerializer(serializers.Serializer):
    """Return editor values and indicate which fields the author may change."""

    trigger_path = serializers.CharField(read_only=True, allow_null=True)
    auto_start = serializers.BooleanField(read_only=True, allow_null=True)
    can_edit_trigger = serializers.BooleanField(read_only=True)
    can_edit_auto_start = serializers.BooleanField(read_only=True)


class RouteSuggestionSerializer(serializers.Serializer):
    """Expose the same labels and URLs offered by the workspace Link picker."""

    url = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)


class RevisionSettingsSerializer(RevisionTriggerSerializer):
    """Supply the settings form and route suggestions together."""

    routes = RouteSuggestionSerializer(many=True, read_only=True)


class UpdateRevisionSettingsSerializer(serializers.Serializer):
    """Accept only the trigger controls submitted by this editor."""

    trigger_path = serializers.CharField(
        max_length=2048, allow_blank=True, required=False
    )
    auto_start = serializers.BooleanField(required=False)


def validate_trigger_path(path: str) -> str:
    """Store a local wildcard path or resolve an exact page to its Django route name."""
    max_length = TutorialRevision._meta.get_field("trigger_route").max_length
    if "*" in path:
        validate_local_step_path(path, "trigger_path")
        if len(path) > max_length:
            raise ValidationError({"trigger_path": _("The wildcard path is too long.")})
        return path

    try:
        page = resolve_step_page(path)
    except ValidationError as error:
        raise ValidationError({"trigger_path": _("Choose a BloomERP page.")}) from error
    name = page["destination_route"]
    if name and (
        page["destination_kwargs"]
        or len(name) > max_length
        or not any(
            route.url_name == name
            and route.route_type
            in {RouteType.APP, RouteType.MODULE, RouteType.MODEL, RouteType.DETAIL}
            and route.nr_of_args() == 0
            and not (route.path or "").lstrip("/").startswith(("api/", "components/"))
            for route in router.get_routes()
        )
    ):
        raise ValidationError({"trigger_path": _("Choose a BloomERP page.")})
    return name


def revision_trigger_values(
    revision: TutorialRevision, permissions: UserPolicyManager
) -> dict[str, str | bool | None]:
    """Display the saved trigger as a path and respect revision field grants."""
    if permissions.user.is_superuser:
        readable = editable = {"trigger_route", "auto_start"}
    else:
        readable = set(
            permissions.get_accessible_fields_for_object(
                revision, BloomerpPermission.VIEW
            ).values_list("field", flat=True)
        )
        editable = readable.intersection(
            permissions.get_accessible_fields_for_object(
                revision, BloomerpPermission.CHANGE
            ).values_list("field", flat=True)
        )

    trigger_path = None
    if "trigger_route" in readable:
        trigger_path = revision.trigger_route
        if trigger_path and not trigger_path.startswith("/"):
            try:
                trigger_path = reverse(trigger_path)
            except NoReverseMatch:
                pass
    return {
        "trigger_path": trigger_path,
        "auto_start": revision.auto_start if "auto_start" in readable else None,
        "can_edit_trigger": "trigger_route" in editable,
        "can_edit_auto_start": "auto_start" in editable,
    }


@router.register(
    path="settings/",
    route_type="api_detail",
    models=[TutorialRevision],
    url_name="tutorial_revision_settings",
    sdk=[
        SdkEndpoint(
            method="GET",
            input_serializer=serializers.Serializer,
            output_serializer=RevisionSettingsSerializer,
        ),
        SdkEndpoint(
            method="PATCH",
            input_serializer=UpdateRevisionSettingsSerializer,
            output_serializer=RevisionTriggerSerializer,
        ),
    ],
)
class TutorialRevisionSettingsView(BaseBloomerpApiView):
    """Manage trigger settings for readable, writable tutorial drafts."""

    model = TutorialRevision
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: UUID | int) -> Response:
        """Return the current settings and the shared route picker choices."""
        permissions = UserPolicyManager(request.user)
        revision = self.model.get_writable(permissions, pk)
        if not permissions.has_access_to_object(revision, BloomerpPermission.VIEW):
            raise PermissionDenied()
        values = {
            **revision_trigger_values(revision, permissions),
            "routes": router.get_link_route_suggestions(),
        }
        return Response(RevisionSettingsSerializer(values).data)

    def patch(self, request: Request, pk: UUID | int) -> Response:
        """Save authorized changes atomically and enforce the automatic trigger requirement."""
        serializer = UpdateRevisionSettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        permissions = UserPolicyManager(request.user)
        with transaction.atomic():
            revision = self.model.get_writable(permissions, pk, lock=True)
            if not permissions.has_access_to_object(revision, BloomerpPermission.VIEW):
                raise PermissionDenied()
            values = revision_trigger_values(revision, permissions)
            changes: dict[str, str | bool] = {}
            if "trigger_path" in data:
                if not values["can_edit_trigger"]:
                    raise PermissionDenied()
                path = data["trigger_path"]
                if path != revision.trigger_route or path.startswith("/"):
                    changes["trigger_route"] = validate_trigger_path(path)
            if "auto_start" in data:
                if not values["can_edit_auto_start"]:
                    raise PermissionDenied()
                changes["auto_start"] = data["auto_start"]
            if changes.get("auto_start", revision.auto_start) and not changes.get(
                "trigger_route", revision.trigger_route
            ):
                raise ValidationError(
                    {
                        "trigger_path": _(
                            "Choose a trigger route to start automatically."
                        )
                    }
                )
            changes = {
                field: value
                for field, value in changes.items()
                if getattr(revision, field) != value
            }
            if changes:
                for field, value in changes.items():
                    setattr(revision, field, value)
                revision.updated_by = request.user
                revision.save(
                    update_fields=[*changes, "updated_by", "datetime_updated"]
                )
        return Response(
            RevisionTriggerSerializer(
                revision_trigger_values(revision, permissions)
            ).data
        )
