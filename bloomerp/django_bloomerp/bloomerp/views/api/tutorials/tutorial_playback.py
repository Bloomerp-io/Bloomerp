"""Start an eligible published tutorial and record how its run ended."""

from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from bloomerp.models.tutorial import TutorialProgress, TutorialRevision
from bloomerp.router import router
from bloomerp.sdk.definition import SdkEndpoint
from bloomerp.serializers.tutorial_step import (
    TutorialRevisionPreviewSerializer,
    TutorialRevisionStepsQuery,
    serialize_preview_step,
    serialize_tutorial_introduction,
)
from bloomerp.views.api.base import BaseBloomerpApiView


class StartTutorialSerializer(TutorialRevisionStepsQuery):
    """Identify the revision and whether it was started by a page trigger."""

    automatic = serializers.BooleanField(required=False, default=False)


class EndTutorialSerializer(TutorialRevisionStepsQuery):
    """Record how the learner left a published tutorial."""

    outcome = serializers.ChoiceField(choices=("completed", "dismissed"))
    step_id = serializers.UUIDField()


@router.register(
    path="tutorials/playback/",
    route_type="api",
    url_name="tutorial_playback",
    sdk=[
        SdkEndpoint(
            method="POST",
            input_serializer=StartTutorialSerializer,
            output_serializer=TutorialRevisionPreviewSerializer,
        ),
        SdkEndpoint(
            method="PATCH",
            input_serializer=EndTutorialSerializer,
            output_serializer=serializers.Serializer,
        ),
    ],
)
class TutorialPlaybackView(BaseBloomerpApiView):
    """Expose published content under the tutorial's learner assignments."""

    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        """Recheck eligibility, claim the launch, and return the presentation."""
        serializer = StartTutorialSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        revision = get_object_or_404(
            TutorialRevision.eligible_for(request.user).select_related("tutorial"),
            pk=data["revision_id"],
        )
        if data["automatic"] and not revision.auto_start:
            return Response(status=409)
        steps = list(revision.steps.order_by("sequence"))
        if not steps:
            raise Http404
        with transaction.atomic():
            progress, _created = (
                TutorialProgress.objects.select_for_update().get_or_create(
                    revision=revision, user=request.user
                )
            )
            if data["automatic"] and any(
                (
                    progress.first_shown_at,
                    progress.started_at,
                    progress.dismissed_at,
                    progress.completed_at,
                )
            ):
                return Response(status=409)
            now = timezone.now()
            progress.first_shown_at = progress.first_shown_at or now
            progress.started_at = progress.started_at or now
            progress.current_step = steps[0]
            progress.save(
                update_fields=[
                    "first_shown_at",
                    "started_at",
                    "current_step",
                    "datetime_updated",
                ]
            )
        return Response(
            TutorialRevisionPreviewSerializer(
                {
                    "introduction": serialize_tutorial_introduction(revision.tutorial),
                    "steps": [serialize_preview_step(step, None) for step in steps],
                }
            ).data,
            headers={"Cache-Control": "private, no-store"},
        )

    def patch(self, request: Request) -> Response:
        """Record a completion or dismissal for the authenticated learner."""
        serializer = EndTutorialSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        revision = get_object_or_404(
            TutorialRevision.eligible_for(request.user), pk=data["revision_id"]
        )
        step = get_object_or_404(revision.steps, pk=data["step_id"])
        progress = get_object_or_404(
            TutorialProgress,
            revision=revision,
            user=request.user,
            started_at__isnull=False,
        )
        field = "completed_at" if data["outcome"] == "completed" else "dismissed_at"
        now = timezone.now()
        TutorialProgress.objects.filter(
            pk=progress.pk, **{f"{field}__isnull": True}
        ).update(**{field: now, "current_step": step, "datetime_updated": now})
        return Response(status=204)
