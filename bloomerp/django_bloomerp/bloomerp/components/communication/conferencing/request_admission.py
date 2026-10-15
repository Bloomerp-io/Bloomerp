"""Browser-bound shared meeting request admission endpoint."""

from uuid import UUID

from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from bloomerp.communication.builtins.conferencing.sharing import (
    request_admission as enqueue,
)
from bloomerp.router import router


@router.register(
    path="components/communication/conferencing/guest/<uuid:token>/request/",
    url_name="components_conferencing_request_admission",
)
@never_cache
@require_POST
def request_admission(request: HttpRequest, token: UUID) -> JsonResponse:
    """Resolve this browser's admission without exposing other visitors or conversation data."""
    try:
        admission = enqueue(request, token)
    except ValidationError as error:
        return JsonResponse({"error": " ".join(error.messages)}, status=400)
    return JsonResponse({"status": admission.status})
