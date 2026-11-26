"""Read, edit, copy, and remove a single step from an authoring draft."""

from uuid import UUID

from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from bloomerp.models.tutorial import TutorialRevision, TutorialStep
from bloomerp.models.tutorial.tutorial_step import TUTORIAL_STEP_CONTENT_FIELDS
from bloomerp.permissions.definition import BloomerpPermission, PermissionMatch
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.sdk.definition import SdkEndpoint
from bloomerp.serializers.tutorial_step import (
    STEP_PAGE_FIELDS,
    TutorialStepFieldsSerializer,
    TutorialStepSummarySerializer,
    resolve_step_page,
    step_page_path,
    validate_step_settings,
)
from bloomerp.utils.rich_text import sanitize_html
from bloomerp.views.api.base import BaseBloomerpApiView


class TutorialStepEditorSerializer(serializers.Serializer):
    """Supply the form values, including the step's interaction configuration."""

    name = serializers.CharField(read_only=True)
    text = serializers.CharField(read_only=True)
    size = serializers.ChoiceField(
        choices=TutorialStep.Size.choices, read_only=True, allow_null=True
    )
    include_backdrop = serializers.BooleanField(read_only=True)
    show_as_tooltip = serializers.BooleanField(read_only=True, allow_null=True)
    advance_mode = serializers.ChoiceField(
        choices=TutorialStep.AdvanceMode.choices, read_only=True, allow_null=True
    )
    advance_delay_ms = serializers.IntegerField(read_only=True, allow_null=True)
    advance_url_pattern = serializers.CharField(read_only=True, allow_null=True)
    hide_next_button = serializers.BooleanField(read_only=True, allow_null=True)
    page_path = serializers.CharField(read_only=True, allow_null=True)
    interaction = serializers.JSONField(read_only=True, allow_null=True)


class UpdateTutorialStepSerializer(TutorialStepFieldsSerializer):
    """Allow the author to change the saved page and highlight independently."""

    page_path = serializers.CharField(max_length=2048, required=False, allow_blank=True)


class TutorialStepRemovalSerializer(serializers.Serializer):
    """Confirm that the step was removed from its revision."""

    deleted = serializers.BooleanField(read_only=True)


class CopyTutorialStepSerializer(serializers.Serializer):
    """Identify the new step so a retried copy request can return the same row."""

    step_id = serializers.UUIDField()


@router.register(
    path="",
    route_type="api_detail",
    models=[TutorialStep],
    url_name="tutorial_step_detail",
    sdk=[
        SdkEndpoint(
            method="GET",
            input_serializer=serializers.Serializer,
            output_serializer=TutorialStepEditorSerializer,
        ),
        SdkEndpoint(
            method="PUT",
            input_serializer=UpdateTutorialStepSerializer,
            output_serializer=TutorialStepSummarySerializer,
        ),
        SdkEndpoint(
            method="POST",
            input_serializer=CopyTutorialStepSerializer,
            output_serializer=TutorialStepSummarySerializer,
        ),
        SdkEndpoint(
            method="DELETE",
            input_serializer=serializers.Serializer,
            output_serializer=TutorialStepRemovalSerializer,
        ),
    ],
)
class TutorialStepDetailView(BaseBloomerpApiView):
    """Manage a step under the permissions of its editable revision and tutorial."""

    model = TutorialStep
    permission_classes = (IsAuthenticated,)

    def get_step(
        self,
        permissions: UserPolicyManager,
        step_id: UUID | int,
        action: BloomerpPermission,
        *,
        lock: bool = False,
    ) -> TutorialStep:
        """Resolve the step in the caller's row scope and lock the draft for mutations."""
        required = [BloomerpPermission.VIEW, action]
        if not permissions.has_global_permission(
            self.model, required, match=PermissionMatch.ALL
        ):
            raise PermissionDenied()
        if not isinstance(step_id, UUID):
            raise Http404

        readable_ids = (
            permissions.get_accessible_queryset(self.model, BloomerpPermission.VIEW)
            .order_by()
            .values("pk")
        )
        visible_steps = permissions.get_accessible_queryset(self.model, action).filter(
            pk__in=readable_ids
        )
        step = get_object_or_404(visible_steps, pk=step_id)
        revision = TutorialRevision.get_writable(
            permissions, step.revision_id, lock=lock
        )
        if lock:
            step = get_object_or_404(
                revision.steps.select_for_update().filter(
                    pk__in=visible_steps.order_by().values("pk")
                ),
                pk=step_id,
            )
        return step

    def get(self, request: Request, pk: UUID | int) -> Response:
        """Load the current step values into the editing modal."""
        permissions = UserPolicyManager(request.user)
        step = self.get_step(permissions, pk, BloomerpPermission.CHANGE)
        fields = {
            *STEP_PAGE_FIELDS,
            "size",
            "show_as_tooltip",
            "advance_mode",
            "advance_delay_ms",
            "advance_url_pattern",
            "hide_next_button",
            "interaction",
        }
        if not request.user.is_superuser:
            fields = set(
                permissions.get_accessible_fields_for_object(
                    step, BloomerpPermission.VIEW
                ).values_list("field", flat=True)
            )
            if not {"text", "include_backdrop"}.issubset(fields):
                raise PermissionDenied()
        page_path = step_page_path(step, fields)
        if page_path is None and {"destination_route", "destination_kwargs"} <= fields:
            page_path = ""
        data = {
            "name": step.name,
            "text": sanitize_html(step.text, allow_images=True),
            "size": step.size if "size" in fields else None,
            "include_backdrop": step.include_backdrop,
            "show_as_tooltip": step.show_as_tooltip if "show_as_tooltip" in fields else None,
            "advance_mode": step.advance_mode if "advance_mode" in fields else None,
            "advance_delay_ms": step.advance_delay_ms
            if "advance_delay_ms" in fields
            else None,
            "advance_url_pattern": step.advance_url_pattern
            if "advance_url_pattern" in fields
            else None,
            "hide_next_button": step.hide_next_button if "hide_next_button" in fields else None,
            "page_path": page_path,
            "interaction": step.interaction if "interaction" in fields else None,
        }
        return Response(TutorialStepEditorSerializer(data).data)

    def put(self, request: Request, pk: UUID | int) -> Response:
        """Save the form while retaining the step order and omitted settings."""
        serializer = UpdateTutorialStepSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        changes = {field: data[field] for field in ("name", "include_backdrop")}
        changes.update(
            (field, data[field])
            for field in (
                "text",
                "size",
                "show_as_tooltip",
                "advance_mode",
                "advance_delay_ms",
                "advance_url_pattern",
                "hide_next_button",
                "interaction",
            )
            if field in data
        )
        if "page_path" in data:
            changes.update(resolve_step_page(data["page_path"]))
        if (
            "advance_mode" in changes
            and changes["advance_mode"] != TutorialStep.AdvanceMode.NAVIGATION
        ):
            changes.setdefault("advance_url_pattern", "")

        permissions = UserPolicyManager(request.user)
        change = BloomerpPermission.CHANGE
        with transaction.atomic():
            step = self.get_step(permissions, pk, change, lock=True)
            validate_step_settings(
                changes.get("advance_mode", step.advance_mode),
                interaction=changes.get("interaction", step.interaction),
                delay_ms=changes.get("advance_delay_ms", step.advance_delay_ms),
                url_pattern=changes.get(
                    "advance_url_pattern", step.advance_url_pattern
                ),
                hide_next_button=changes.get("hide_next_button", False),
                show_as_tooltip=changes.get("show_as_tooltip", step.show_as_tooltip),
                include_backdrop=changes["include_backdrop"],
            )
            changed_fields = [
                field
                for field, value in changes.items()
                if getattr(step, field) != value
            ]
            if changed_fields:
                if (
                    not request.user.is_superuser
                    and not permissions.has_access_to_object(
                        step, change, fields=changed_fields
                    )
                ):
                    raise PermissionDenied()
                for field in changed_fields:
                    setattr(step, field, changes[field])
                step.updated_by = request.user
                step.save(
                    update_fields=[*changed_fields, "updated_by", "datetime_updated"]
                )
                if (
                    not request.user.is_superuser
                    and not permissions.has_access_to_object(
                        step, change, fields=changed_fields
                    )
                ):
                    raise PermissionDenied()

        return Response(TutorialStepSummarySerializer(step).data)

    def post(self, request: Request, pk: UUID | int) -> Response:
        """Append a copy of the source step to the same editable draft."""
        serializer = CopyTutorialStepSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        permissions = UserPolicyManager(request.user)
        view, add = BloomerpPermission.VIEW, BloomerpPermission.ADD
        if not permissions.has_global_permission(self.model, add):
            raise PermissionDenied()

        key = serializer.validated_data["step_id"].hex
        fields = list(TUTORIAL_STEP_CONTENT_FIELDS)
        with transaction.atomic():
            source = self.get_step(permissions, pk, view, lock=True)
            if not request.user.is_superuser and not permissions.has_access_to_object(
                source, view, fields=[field for field in fields if field != "name"]
            ):
                raise PermissionDenied()

            revision = source.revision
            existing = revision.steps.filter(key=key).first()
            if existing is not None:
                if existing.created_by_id != request.user.pk or not permissions.has_access_to_object(
                    existing, add, fields=None if request.user.is_superuser else fields
                ):
                    raise PermissionDenied()
                return Response(TutorialStepSummarySerializer(existing).data)

            step = self.model(
                revision=revision,
                key=key,
                sequence=revision.next_step_sequence(),
                created_by=request.user,
                updated_by=request.user,
                **{field: getattr(source, field) for field in fields},
            )
            if not permissions.candidate_matches_row_policies(step, add):
                raise PermissionDenied()
            step.save()
            if not request.user.is_superuser and not permissions.has_access_to_object(
                step, add, fields=fields
            ):
                raise PermissionDenied()

        return Response(TutorialStepSummarySerializer(step).data, status=201)

    def delete(self, request: Request, pk: UUID | int) -> Response:
        """Remove the selected step without renumbering the remaining steps."""
        permissions = UserPolicyManager(request.user)
        with transaction.atomic():
            step = self.get_step(permissions, pk, BloomerpPermission.DELETE, lock=True)
            step.delete()
        return Response(TutorialStepRemovalSerializer({"deleted": True}).data)
