"""Host-only admission decisions shared by all conference origins."""

from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from bloomerp.communication.builtins.conferencing.sharing import (
    decide_admission as decide,
)
from bloomerp.router import router


@router.register(
    path="components/communication/conferencing/<uuid:session_id>/admit/<uuid:admission_id>/",
    url_name="components_conferencing_decide_admission",
)
@login_required
@never_cache
@require_POST
def decide_admission(
    request: HttpRequest, session_id: UUID, admission_id: UUID
) -> JsonResponse:
    """Admit or reject one waiting visitor after rechecking host authority."""
    try:
        decide(request, session_id, admission_id)
    except ValidationError as error:
        return JsonResponse({"error": " ".join(error.messages)}, status=400)
    return JsonResponse({"ok": True})
