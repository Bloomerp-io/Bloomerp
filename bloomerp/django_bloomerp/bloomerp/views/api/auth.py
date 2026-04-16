from __future__ import annotations

import json

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.http import HttpRequest, JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.http import require_GET, require_POST

from bloomerp.config.definition import BloomerpConfig, SessionAuthSettings


def get_bloomerp_config() -> BloomerpConfig:
    config = getattr(settings, "BLOOMERP_CONFIG", None)
    if isinstance(config, BloomerpConfig):
        return config
    return BloomerpConfig()


def _session_auth_settings() -> SessionAuthSettings:
    return get_bloomerp_config().auth.session


def _session_auth_enabled() -> bool:
    return _session_auth_settings().enabled


def _json_not_found(message: str) -> JsonResponse:
    return JsonResponse({"detail": message}, status=404)


def _parse_request_data(request: HttpRequest) -> dict:
    if request.content_type and "application/json" in request.content_type:
        try:
            raw_body = request.body.decode("utf-8") if request.body else "{}"
            return json.loads(raw_body or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
    return request.POST.dict()


def _serialize_user(user) -> dict:
    payload: dict[str, object] = {}
    for field_name in _session_auth_settings().user_fields:
        if hasattr(user, field_name):
            payload[field_name] = getattr(user, field_name)
    return payload


def _get_login_credentials(data: dict) -> dict[str, object]:
    session_settings = _session_auth_settings()
    identifier_field_name = session_settings.get_identifier_field_name()
    identifier_value = data.get(identifier_field_name, data.get("identifier"))
    password = data.get("password")

    credentials: dict[str, object] = {}
    if password is not None:
        credentials["password"] = password

    if identifier_value is None:
        return credentials

    user_model = get_user_model()

    if session_settings.login_identifier == "email":
        username_field = getattr(user_model, "USERNAME_FIELD", "username")
        user = user_model._default_manager.filter(email__iexact=identifier_value).first()
        if user is not None:
            credentials[username_field] = getattr(user, username_field)
            return credentials

    credentials[identifier_field_name] = identifier_value
    return credentials


@require_GET
def session_view(request: HttpRequest) -> JsonResponse:
    if not _session_auth_enabled():
        return _json_not_found("Session auth endpoints are disabled.")

    if not request.user.is_authenticated:
        return JsonResponse({"authenticated": False})

    return JsonResponse(
        {
            "authenticated": True,
            "user": _serialize_user(request.user),
        }
    )


@require_GET
def csrf_view(request: HttpRequest) -> JsonResponse:
    if not _session_auth_enabled():
        return _json_not_found("Session auth endpoints are disabled.")

    return JsonResponse({"csrfToken": get_token(request)})


@require_POST
def login_view(request: HttpRequest) -> JsonResponse:
    if not _session_auth_enabled():
        return _json_not_found("Session auth endpoints are disabled.")

    data = _parse_request_data(request)
    credentials = _get_login_credentials(data)
    user = authenticate(request, **credentials)

    if user is None:
        return JsonResponse(
            {
                "authenticated": False,
                "detail": "Invalid credentials.",
            },
            status=400,
        )

    login(request, user)
    return JsonResponse(
        {
            "authenticated": True,
            "user": _serialize_user(user),
        }
    )


@require_POST
def logout_view(request: HttpRequest) -> JsonResponse:
    if not _session_auth_enabled():
        return _json_not_found("Session auth endpoints are disabled.")

    logout(request)
    return JsonResponse({"authenticated": False})
