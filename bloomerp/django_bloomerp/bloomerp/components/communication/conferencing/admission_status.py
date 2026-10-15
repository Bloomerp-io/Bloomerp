"""Browser-bound shared meeting admission status endpoint."""

from uuid import UUID

from django.http import HttpRequest, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from bloomerp.communication.builtins.conferencing.sharing import (
    browser_admission,
    shared_session,
)
from bloomerp.router import router


@router.register(
    path="components/communication/conferencing/guest/<uuid:token>/status/",
    url_name="components_conferencing_admission_status",
)
@never_cache
@require_GET
def admission_status(request: HttpRequest, token: UUID) -> JsonResponse:
    """Resolve this browser's admission without exposing other visitors or conversation data."""
    session = shared_session(token)
    admission = browser_admission(request, session)
    return JsonResponse({"status": admission.status if admission else "new"})
