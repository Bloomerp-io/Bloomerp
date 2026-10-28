"""One registered callback for every email provider authorization strategy."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
)
from django.views.decorators.http import require_GET

from bloomerp.communication.builtins.emails.authorization import complete_authorization
from bloomerp.router import router


@router.register(
    path="communication/email/authorize/callback/",
    url_name="email_authorization_callback",
)
@require_GET
def email_authorization_callback(request: HttpRequest) -> HttpResponse:
    """Complete only an authenticated, expiring, single-use mailbox authorization."""
    try:
        response = complete_authorization(request)
    except ValidationError:
        response = HttpResponseBadRequest(
            "The email authorization callback is not configured for this instance."
        )
    except PermissionDenied:
        response = HttpResponseForbidden("This email authorization request is invalid or has expired.")
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response
