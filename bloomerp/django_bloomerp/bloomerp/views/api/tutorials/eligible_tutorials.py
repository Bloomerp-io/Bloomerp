"""List route hints for published tutorials without returning their steps."""

from django.contrib.auth.base_user import AbstractBaseUser
from django.db.models import Exists, OuterRef, Q
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from bloomerp.models.tutorial import TutorialProgress, TutorialRevision
from bloomerp.router import router
from bloomerp.sdk.definition import SdkEndpoint
from bloomerp.views.api.base import BaseBloomerpApiView


class EligibleTutorialSerializer(serializers.Serializer):
    """Provide the route and label needed to offer a tutorial without its steps."""

    revision_id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    trigger_route = serializers.CharField(read_only=True)
    auto_start = serializers.BooleanField(read_only=True)


class EligibleTutorialsSerializer(serializers.Serializer):
    """Return a small catalog of the tutorials this user can start."""

    tutorials = EligibleTutorialSerializer(many=True, read_only=True)


def tutorial_already_shown(user: AbstractBaseUser) -> Exists:
    """Identify revisions that have already been offered to this learner."""
    return Exists(
        TutorialProgress.objects.filter(user=user, revision_id=OuterRef("pk")).filter(
            Q(first_shown_at__isnull=False)
            | Q(started_at__isnull=False)
            | Q(dismissed_at__isnull=False)
            | Q(completed_at__isnull=False)
        )
    )


@router.register(
    path="tutorials/eligible/",
    route_type="api",
    url_name="eligible_tutorials",
    sdk=SdkEndpoint(
        method="GET",
        input_serializer=serializers.Serializer,
        output_serializer=EligibleTutorialsSerializer,
    ),
)
class EligibleTutorialsView(BaseBloomerpApiView):
    """Return the signed-in learner's current tutorial catalog."""

    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        """Return route metadata and offer each automatic revision only once."""
        revisions = (
            TutorialRevision.eligible_for(request.user)
            .select_related("tutorial")
            .annotate(already_shown=tutorial_already_shown(request.user))
            .order_by("tutorial__name", "pk")
        )
        tutorials = [
            {
                "revision_id": revision.pk,
                "name": revision.tutorial.name,
                "trigger_route": revision.trigger_route,
                "auto_start": revision.auto_start and not revision.already_shown,
            }
            for revision in revisions
        ]
        return Response(
            EligibleTutorialsSerializer({"tutorials": tutorials}).data,
            headers={"Cache-Control": "private, no-store"},
        )
