"""Connection-owner management of local business-line assignments."""

from uuid import UUID
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST
from django.utils.translation import gettext as _
from bloomerp.router import router
from bloomerp.communication.builtins.voip.access import VoIPAccessManager
from bloomerp.models.communication.voip import VoIPNumber


@router.register(
    path="components/communication/voip/numbers/<uuid:number_id>/assign/",
    url_name="components_voip_assign",
)
@login_required
@require_POST
def assign_number(request: HttpRequest, number_id: UUID) -> HttpResponse:
    """Assign only existing active staff and reject unauthorized connection changes."""
    number = get_object_or_404(
        VoIPNumber.objects.filter(
            connection__in=VoIPAccessManager(request.user).get_connections()
        ),
        pk=number_id,
    )
    ids = {value.strip() for value in request.POST.getlist("users") if value.strip()}
    try:
        users = list(
            get_user_model().objects.filter(pk__in=ids, is_active=True, is_staff=True)
        )
    except (ValueError, TypeError):
        return HttpResponse(status=400)
    if len(users) != len(ids):
        return HttpResponse(_("Select active staff users."), status=400)
    try:
        with transaction.atomic():
            number.assigned_users.set(users)
    except ValidationError as error:
        return HttpResponse("; ".join(error.messages), status=400)
    from bloomerp.models.communication.inbox.inbox_item import InboxItem

    revoked = number.conversations.values("pk")
    InboxItem.objects.filter(
        item_type="instant_messaging_item", related_item_id__in=revoked
    ).exclude(folder__inbox__user__in=users).exclude(
        folder__inbox__user__is_superuser=True
    ).delete()
    return HttpResponse(_("Assignments saved."))
