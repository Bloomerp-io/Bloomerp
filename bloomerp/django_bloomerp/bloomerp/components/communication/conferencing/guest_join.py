"""Browser-bound shared meeting guest join endpoint."""

from uuid import UUID

from django.http import HttpRequest, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from bloomerp.communication.builtins.conferencing.sharing import guest_credentials
from bloomerp.router import router


@router.register(
    path="components/communication/conferencing/guest/<uuid:token>/join/",
    url_name="components_conferencing_guest_join",
)
@never_cache
@require_POST
def guest_join(request: HttpRequest, token: UUID) -> JsonResponse:
    """Resolve this browser's admission without exposing other visitors or conversation data."""
    return JsonResponse(guest_credentials(request, token))
