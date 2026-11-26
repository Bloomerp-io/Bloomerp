"""Save the authored order of a tutorial draft's steps."""

from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.status import HTTP_409_CONFLICT

from bloomerp.models.tutorial import TutorialRevision, TutorialStep
from bloomerp.permissions.definition import BloomerpPermission, PermissionMatch
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.sdk.definition import SdkEndpoint
from bloomerp.serializers.tutorial_step import (
    ReorderTutorialStepsSerializer,
    TutorialRevisionStepsSerializer,
)
from bloomerp.views.api.base import BaseBloomerpApiView


def save_tutorial_step_sequences(
    revision: TutorialRevision,
    updates: list[tuple[TutorialStep, int]],
    occupied_sequences: set[int],
    actor: AbstractBaseUser,
) -> None:
    """Swap sequence values via free positions inside the caller's draft transaction."""
    changed_steps = []
    spare_sequence = 0
    for step, _sequence in updates:
        while spare_sequence in occupied_sequences:
            spare_sequence += 1
        step.sequence = spare_sequence
        changed_steps.append(step)
        spare_sequence += 1
    revision.steps.bulk_update(changed_steps, ["sequence"])

    updated_at = timezone.now()
    for step, sequence in updates:
        step.sequence = sequence
        step.updated_by = actor
        step.datetime_updated = updated_at
    revision.steps.bulk_update(
        changed_steps, ["sequence", "updated_by", "datetime_updated"]
    )


@router.register(
    path="steps/reorder/",
    route_type="api_detail",
    models=[TutorialRevision],
    url_name="reorder_tutorial_steps",
    sdk=SdkEndpoint(
        method="POST",
        input_serializer=ReorderTutorialStepsSerializer,
        output_serializer=TutorialRevisionStepsSerializer,
    ),
)
class ReorderTutorialStepsView(BaseBloomerpApiView):
    """Reorder a complete set of viewable steps in an editable draft."""

    model = TutorialRevision
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: UUID | int) -> Response:
        """Write the requested order atomically and return the resulting sequence."""
        serializer = ReorderTutorialStepsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        permissions = UserPolicyManager(request.user)
        view, change = BloomerpPermission.VIEW, BloomerpPermission.CHANGE
        if not permissions.has_global_permission(
            TutorialStep, [view, change], match=PermissionMatch.ALL
        ):
            raise PermissionDenied()

        with transaction.atomic():
            revision = self.model.get_writable(permissions, pk, lock=True)
            if not permissions.has_access_to_object(revision, view):
                raise PermissionDenied()

            steps = list(revision.steps.select_for_update().order_by("sequence"))
            steps_by_id = {step.pk: step for step in steps}
            read_scope = revision.steps_with_sequence_access(permissions, view)
            if not steps_by_id.keys() <= set(read_scope.values_list("pk", flat=True)):
                raise PermissionDenied()
            if steps_by_id.keys() != set(data["step_ids"]):
                return Response(
                    {"detail": _("The steps changed. Reload the list and try again.")},
                    status=HTTP_409_CONFLICT,
                )

            ordered_steps = [steps_by_id[step_id] for step_id in data["step_ids"]]
            occupied_sequences = [step.sequence for step in steps]
            updates = [
                (step, sequence)
                for step, sequence in zip(
                    ordered_steps, occupied_sequences, strict=True
                )
                if step.sequence != sequence
            ]
            if updates:
                updated_ids = {step.pk for step, _ in updates}
                write_scope = revision.steps_with_sequence_access(permissions, change)
                if not updated_ids <= set(write_scope.values_list("pk", flat=True)):
                    raise PermissionDenied()

                save_tutorial_step_sequences(
                    revision, updates, set(occupied_sequences), request.user
                )
                if not updated_ids <= set(
                    write_scope.values_list("pk", flat=True)
                ) or not steps_by_id.keys() <= set(
                    read_scope.values_list("pk", flat=True)
                ):
                    raise PermissionDenied()

            return Response(
                TutorialRevisionStepsSerializer({"steps": ordered_steps}).data
            )
