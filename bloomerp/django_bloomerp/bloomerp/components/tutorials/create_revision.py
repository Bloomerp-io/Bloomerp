"""Start a new draft revision for a tutorial author."""

from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from bloomerp.models.tutorial import Tutorial, TutorialRevision
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router


@router.register(
    path="components/tutorials/<uuid:tutorial_id>/revisions/create/",
    url_name="components_tutorials_create_revision",
)
@login_required
@require_POST
def create_tutorial_revision(request: HttpRequest, tutorial_id: UUID) -> JsonResponse:
    """Allocate the next draft revision number and return its ID to the editor."""
    permissions = UserPolicyManager(request.user)
    visible_ids = (
        permissions.get_accessible_queryset(Tutorial, BloomerpPermission.VIEW)
        .order_by()
        .values("pk")
    )
    with transaction.atomic():
        tutorial = get_object_or_404(
            Tutorial.objects.select_for_update().filter(pk__in=visible_ids),
            pk=tutorial_id,
        )
        if not tutorial.can_create_revision(request.user):
            raise PermissionDenied

        last_number = tutorial.revisions.values_list("number", flat=True).first() or 0
        revision = TutorialRevision(
            tutorial=tutorial, number=last_number + 1, created_by=request.user
        )
        if not permissions.candidate_matches_row_policies(
            revision, BloomerpPermission.ADD
        ):
            raise PermissionDenied
        revision.save()

    return JsonResponse({"revision_id": str(revision.pk)}, status=201)
