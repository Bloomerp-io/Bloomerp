"""Expose the step summaries for one tutorial revision in the authoring panel."""

from uuid import UUID

from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from bloomerp.models.tutorial import TutorialRevision, TutorialStep
from bloomerp.permissions.definition import BloomerpPermission, PermissionMatch
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.sdk.definition import SdkEndpoint
from bloomerp.serializers.tutorial_step import TutorialRevisionStepsSerializer
from bloomerp.views.api.base import BaseBloomerpApiView


@router.register(
    path="steps/",
    route_type="api_detail",
    models=[TutorialRevision],
    url_name="tutorial_revision_steps",
    sdk=SdkEndpoint(
        method="GET",
        input_serializer=serializers.Serializer,
        output_serializer=TutorialRevisionStepsSerializer,
    ),
)
class TutorialRevisionStepsView(BaseBloomerpApiView):
    """List readable steps for authors who can edit the parent tutorial."""

    model = TutorialRevision
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: UUID | int) -> Response:
        """Return viewable steps with a readable sequence in sequence order."""
        permissions = UserPolicyManager(request.user)
        view = BloomerpPermission.VIEW
        if not (
            permissions.has_global_permission(self.model, view)
            and permissions.has_global_permission(TutorialStep, view)
        ):
            raise PermissionDenied()
        if not isinstance(pk, UUID):
            raise Http404

        revision = get_object_or_404(
            permissions.get_accessible_queryset(self.model, view).select_related(
                "tutorial"
            ),
            pk=pk,
        )
        if not permissions.has_access_to_object(
            revision.tutorial,
            [view, BloomerpPermission.CHANGE],
            match=PermissionMatch.ALL,
        ):
            raise PermissionDenied()

        steps = revision.steps_with_sequence_access(permissions, view)
        rows = steps.order_by("sequence").values("id", "sequence", "name")
        return Response(TutorialRevisionStepsSerializer({"steps": rows}).data)
