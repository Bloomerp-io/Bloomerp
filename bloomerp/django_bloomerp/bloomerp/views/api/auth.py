from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.db import IntegrityError
from django.db.models.fields.files import FieldFile
from django.http import HttpRequest, JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.http import require_GET, require_POST

from bloomerp.config.definition import BloomerpConfig, SessionAuthSettings
from bloomerp.forms.auth import get_user_creation_fields


def get_bloomerp_config() -> BloomerpConfig:
    config = getattr(settings, "BLOOMERP_CONFIG", None)
    if isinstance(config, BloomerpConfig):
        return config
    return BloomerpConfig()


def _session_auth_settings() -> SessionAuthSettings:
    return get_bloomerp_config().auth.session


def _session_auth_enabled() -> bool:
    return _session_auth_settings().enabled


def _interactive_auth_settings():
    return get_bloomerp_config().auth.interactive


def _registration_endpoint_enabled() -> bool:
    interactive = _interactive_auth_settings()
    return bool(interactive.signup_enabled)


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
            payload[field_name] = _serialize_user_field_value(getattr(user, field_name))
    return payload


def _serialize_user_field_value(value: Any) -> object:
    if isinstance(value, FieldFile):
        if not value:
            return None
        try:
            return value.url
        except ValueError:
            return None

    if hasattr(value, "pk") and not isinstance(value, (str, bytes)):
        return value.pk

    return value


def _uses_case_insensitive_lookup(field_name: str) -> bool:
    user_model = get_user_model()
    try:
        field = user_model._meta.get_field(field_name)
    except Exception:
        return False

    internal_type = getattr(field, "get_internal_type", lambda: "")()
    return internal_type in {"CharField", "EmailField", "TextField"}


def _get_registration_payload(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    user_model = get_user_model()
    required_fields = get_user_creation_fields(user_model)
    username_field = getattr(user_model, "USERNAME_FIELD", "username")
    registration_data: dict[str, Any] = {}
    missing_fields: list[str] = []

    for field_name in required_fields:
        value = data.get(field_name)
        if field_name == username_field and value is None:
            value = data.get("identifier")

        if value in (None, ""):
            missing_fields.append(field_name)
            continue

        registration_data[field_name] = value

    for field_name, value in data.items():
        if field_name in {"password", "passwordConfirm", "password_confirmation", "identifier"}:
            continue
        if field_name in registration_data:
            continue
        if hasattr(user_model, field_name):
            registration_data[field_name] = value

    return registration_data, missing_fields


def _find_existing_unique_field(field_name: str, value: Any):
    user_model = get_user_model()
    try:
        field = user_model._meta.get_field(field_name)
    except Exception:
        return None

    if not getattr(field, "unique", False):
        return None

    lookup = (
        {f"{field_name}__iexact": value}
        if isinstance(value, str) and _uses_case_insensitive_lookup(field_name)
        else {field_name: value}
    )
    return user_model._default_manager.filter(**lookup).first()


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
def register_view(request: HttpRequest) -> JsonResponse:
    if not _registration_endpoint_enabled():
        return _json_not_found("Registration endpoints are disabled.")

    data = _parse_request_data(request)
    password = data.get("password")
    password_confirmation = data.get("passwordConfirm", data.get("password_confirmation"))

    if not password:
        return JsonResponse({"detail": "Password is required."}, status=400)

    if password_confirmation is not None and password != password_confirmation:
        return JsonResponse({"detail": "Passwords do not match."}, status=400)

    user_model = get_user_model()
    registration_data, missing_fields = _get_registration_payload(data)
    if missing_fields:
        field_list = ", ".join(missing_fields)
        return JsonResponse(
            {"detail": f"Missing required registration fields: {field_list}."},
            status=400,
        )

    for field_name, value in registration_data.items():
        existing_user = _find_existing_unique_field(field_name, value)
        if existing_user is not None:
            return JsonResponse(
                {"detail": f"An account with this {field_name} already exists."},
                status=400,
            )

    try:
        user_model._default_manager.create_user(
            password=password,
            **registration_data,
        )
    except TypeError as exc:
        return JsonResponse(
            {"detail": f"Registration payload is incompatible with the configured user model: {exc}."},
            status=400,
        )
    except IntegrityError:
        return JsonResponse(
            {"detail": "Unable to create account with the provided credentials."},
            status=400,
        )

    credentials = _get_login_credentials(data)
    user = authenticate(request, **credentials)
    if user is None:
        return JsonResponse(
            {"detail": "Account created, but automatic sign-in failed."},
            status=201,
        )

    login(request, user)
    return JsonResponse(
        {
            "authenticated": True,
            "user": _serialize_user(user),
        },
        status=201,
    )


@require_POST
def logout_view(request: HttpRequest) -> JsonResponse:
    if not _session_auth_enabled():
        return _json_not_found("Session auth endpoints are disabled.")

    logout(request)
    return JsonResponse({"authenticated": False})
