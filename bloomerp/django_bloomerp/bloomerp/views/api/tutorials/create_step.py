"""Save an authored step to a draft tutorial revision."""

from typing import Any
from uuid import UUID

from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from bloomerp.models.tutorial import TutorialRevision, TutorialStep
from bloomerp.models.tutorial.tutorial_step import empty_tutorial_step_interaction
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.sdk.definition import SdkEndpoint
from bloomerp.serializers.tutorial_step import (
    TutorialStepFieldsSerializer,
    TutorialStepSummarySerializer,
    resolve_step_page,
    validate_step_settings,
)
from bloomerp.views.api.base import BaseBloomerpApiView


class CreateTutorialStepSerializer(TutorialStepFieldsSerializer):
    """Validate the fields authored in the tutorial step modal."""

    step_id = serializers.UUIDField()
    page_path = serializers.CharField(max_length=2048, allow_blank=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Check the highlight and automatic advance options for a new step."""
        validate_step_settings(
            attrs.get("advance_mode", TutorialStep.AdvanceMode.MANUAL),
            interaction=attrs.get("interaction", empty_tutorial_step_interaction()),
            delay_ms=attrs.get("advance_delay_ms", 0),
            url_pattern=attrs.get("advance_url_pattern", ""),
            hide_next_button=attrs.get("hide_next_button", False),
            show_as_tooltip=attrs.get("show_as_tooltip", False),
            include_backdrop=attrs["include_backdrop"],
        )
        return attrs


@router.register(
    path="steps/create/",
    route_type="api_detail",
    models=[TutorialRevision],
    url_name="create_tutorial_step",
    sdk=SdkEndpoint(
        method="POST",
        input_serializer=CreateTutorialStepSerializer,
        output_serializer=TutorialStepSummarySerializer,
    ),
)
class CreateTutorialStepView(BaseBloomerpApiView):
    """Append a step to a writable draft under the tutorial's permissions."""

    model = TutorialRevision
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: UUID | int) -> Response:
        """Save an authored step once and allocate its sequence within the revision."""
        serializer = CreateTutorialStepSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        permissions = UserPolicyManager(request.user)
        add = BloomerpPermission.ADD
        if not permissions.has_global_permission(TutorialStep, add):
            raise PermissionDenied()

        with transaction.atomic():
            revision = self.model.get_writable(permissions, pk, lock=True)

            key = data["step_id"].hex
            step = revision.steps.filter(key=key).first()
            if step is not None:
                if (
                    step.created_by_id != request.user.pk
                    or not permissions.has_access_to_object(step, add)
                ):
                    raise PermissionDenied()
                return Response(TutorialStepSummarySerializer(step).data)

            page = resolve_step_page(data["page_path"])
            step = TutorialStep(
                revision=revision,
                key=key,
                sequence=revision.next_step_sequence(),
                name=data["name"],
                text=data.get("text", ""),
                size=data.get("size", TutorialStep.Size.SMALL),
                include_backdrop=data["include_backdrop"],
                show_as_tooltip=data.get("show_as_tooltip", False),
                advance_mode=data.get("advance_mode", TutorialStep.AdvanceMode.MANUAL),
                advance_delay_ms=data.get("advance_delay_ms", 0),
                advance_url_pattern=data.get("advance_url_pattern", ""),
                hide_next_button=data.get("hide_next_button", False),
                **page,
                interaction=data.get("interaction", empty_tutorial_step_interaction()),
                created_by=request.user,
                updated_by=request.user,
            )
            if not permissions.candidate_matches_row_policies(step, add):
                raise PermissionDenied()

            step.save()
            if not request.user.is_superuser:
                fields = [
                    "name",
                    "include_backdrop",
                    "destination_route",
                    "destination_kwargs",
                ]
                fields.extend(
                    field
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
                if not permissions.has_access_to_object(step, add, fields=fields):
                    raise PermissionDenied()

        return Response(TutorialStepSummarySerializer(step).data, status=201)
