"""Expose the waiting list only to the currently authorized meeting host."""

from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from bloomerp.communication.builtins.conferencing.sharing import host_session
from bloomerp.router import router


@router.register(
    path="components/communication/conferencing/<uuid:session_id>/waiting/",
    url_name="components_conferencing_waiting",
)
@login_required
@never_cache
@require_GET
def waiting(request: HttpRequest, session_id: UUID) -> JsonResponse:
    """Return bounded names and decision endpoints without guest browser credentials."""
    session = host_session(request, session_id)
    return JsonResponse(
        {
            "guests": [
                {
                    "id": str(item.pk),
                    "name": item.display_name,
                    "url": reverse(
                        "components_conferencing_decide_admission",
                        kwargs={"session_id": session.pk, "admission_id": item.pk},
                    ),
                }
                for item in session.admissions.filter(status="waiting").order_by("pk")[
                    :100
                ]
            ]
        }
    )
