"""Sign capabilities and expose their verified request-local grants to permission managers."""

from django.core import signing
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest
from django.utils import timezone
from pydantic import ValidationError

from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.definition import BloomerpPermission, PermissionToken

PERMISSION_TOKEN_PARAM = "_permission_token"
PERMISSION_TOKEN_SALT = "bloomerp.permissions.capability.v1"


def permission_name(permission: BloomerpPermission | str) -> str:
    """Serialize permission enums as portable codenames rather than enum dataclasses."""
    return permission.value.codename if isinstance(permission, BloomerpPermission) else permission


def sign_permission_token(token: PermissionToken) -> str:
    """Sign a server-authorized grant; callers must establish their delegation authority."""
    payload = token.model_dump(mode="json", exclude={"rule"})
    payload["rule"] = {
        "row_permissions": [
            {**row.model_dump(mode="json", exclude={"permissions"}),
             "permissions": [permission_name(value) for value in row.permissions]}
            for row in token.rule.row_permissions
        ],
        "field_permissions": {
            field: [permission_name(value) for value in values]
            for field, values in token.rule.field_permissions.items()
        },
    }
    return signing.dumps(payload, salt=PERMISSION_TOKEN_SALT, compress=True)


def verify_permission_token(token: str, *, audience: str | None = None) -> PermissionToken:
    """Reject malformed, altered, expired, or differently addressed capabilities."""
    try:
        grant = PermissionToken.model_validate(signing.loads(token, salt=PERMISSION_TOKEN_SALT))
    except (signing.BadSignature, ValidationError, ValueError, TypeError) as error:
        raise PermissionDenied("Invalid permission token") from error
    if grant.expiry <= timezone.now():
        raise PermissionDenied("Permission token expired")
    if not grant.public and grant.audience != audience:
        raise PermissionDenied("Permission token belongs to another user")
    return grant


def request_permission_token(user: AbstractBloomerpUser | None) -> str | None:
    """Extract a token only for the current HTTP request's user, never another principal."""
    from bloomerp.middleware import current_request

    request = current_request()
    if request is None or getattr(request, "user", None) != user:
        return None
    values = request.GET.getlist(PERMISSION_TOKEN_PARAM)
    if request.method == "POST":
        values += request.POST.getlist(PERMISSION_TOKEN_PARAM)
    if not values:
        return None
    if not values[0] or any(value != values[0] for value in values):
        raise PermissionDenied("Conflicting permission tokens")
    return values[0]


def permission_token_url(request: HttpRequest, url: str) -> str:
    """Carry a request capability to same-origin action endpoints without exposing it externally."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    token = request_permission_token(request.user)
    parts = urlsplit(url)
    if (token is None or (parts.netloc and parts.netloc != request.get_host())
            or (parts.scheme and parts.scheme != request.scheme)):
        return url
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if key != PERMISSION_TOKEN_PARAM]
    query.append((PERMISSION_TOKEN_PARAM, token))
    return urlunsplit(parts._replace(query=urlencode(query)))
