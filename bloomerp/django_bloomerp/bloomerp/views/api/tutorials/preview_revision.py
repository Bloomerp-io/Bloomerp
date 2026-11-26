"""Load a draft's presentation for its author."""

from uuid import UUID

from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from bloomerp.models.application_field import ApplicationField
from bloomerp.models.tutorial import TutorialRevision, TutorialStep
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager, field_access_annotation_name
from bloomerp.router import router
from bloomerp.sdk.definition import SdkEndpoint
from bloomerp.serializers.tutorial_step import (
    PREVIEW_FIELDS,
    TutorialRevisionPreviewSerializer,
    serialize_preview_step,
    serialize_tutorial_introduction,
)
from bloomerp.views.api.base import BaseBloomerpApiView


@router.register(
    path="preview/",
    route_type="api_detail",
    models=[TutorialRevision],
    url_name="preview_tutorial_revision",
    sdk=SdkEndpoint(
        method="GET",
        input_serializer=serializers.Serializer,
        output_serializer=TutorialRevisionPreviewSerializer,
    ),
)
class PreviewTutorialRevisionView(BaseBloomerpApiView):
    """Read a draft presentation under the tutorial and step access policies."""

    model = TutorialRevision
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: UUID | int) -> Response:
        """Return readable introduction and step content for the draft preview."""
        permissions = UserPolicyManager(request.user)
        view = BloomerpPermission.VIEW
        revision = self.model.get_writable(permissions, pk)
        if not (
            permissions.has_access_to_object(revision, view)
            and permissions.has_global_permission(TutorialStep, view)
        ):
            raise PermissionDenied()

        steps = revision.steps_with_sequence_access(permissions, view)
        field_annotations = None
        if not request.user.is_superuser:
            fields = list(
                ApplicationField.get_for_model(TutorialStep).filter(
                    field__in=PREVIEW_FIELDS
                )
            )
            field_annotations = {
                field.field: field_access_annotation_name(field) for field in fields
            }
            steps = permissions.annotate_field_permissions(steps, fields, view)

        rows = [
            serialize_preview_step(step, field_annotations)
            for step in steps.order_by("sequence")
        ]
        tutorial = revision.tutorial
        introduction = serialize_tutorial_introduction(
            tutorial,
            include_description=request.user.is_superuser
            or permissions.has_access_to_object(tutorial, view, fields=["description"]),
        )
        return Response(
            TutorialRevisionPreviewSerializer({"introduction": introduction, "steps": rows}).data
        )
