from __future__ import annotations

import json
from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models.fields.files import FieldFile
from django.http import HttpRequest, JsonResponse
from rest_framework.permissions import AllowAny

from bloomerp.config.definition import SessionAuthSettings, get_bloomerp_config
from bloomerp.forms.auth import get_user_creation_fields
from bloomerp.views.api.base import BaseBloomerpApiView


class BaseSessionAuthApiView(BaseBloomerpApiView):
    permission_classes = (AllowAny,)


def session_auth_settings() -> SessionAuthSettings:
    return get_bloomerp_config().auth.session


def session_auth_enabled() -> bool:
    return session_auth_settings().enabled


def interactive_auth_settings():
    return get_bloomerp_config().auth.interactive


def registration_endpoint_enabled() -> bool:
    interactive = interactive_auth_settings()
    return bool(interactive.signup_enabled)


def json_not_found(message: str) -> JsonResponse:
    return JsonResponse({"detail": message}, status=404)


def parse_request_data(request: HttpRequest) -> dict:
    if request.content_type and "application/json" in request.content_type:
        try:
            raw_body = request.body.decode("utf-8") if request.body else "{}"
            return json.loads(raw_body or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
    return request.POST.dict()


def serialize_user(user) -> dict:
    payload: dict[str, object] = {}
    for field_name in session_auth_settings().user_fields:
        if hasattr(user, field_name):
            payload[field_name] = serialize_user_field_value(getattr(user, field_name))
    return payload


def serialize_user_field_value(value: Any) -> object:
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


def uses_case_insensitive_lookup(field_name: str) -> bool:
    user_model = get_user_model()
    try:
        field = user_model._meta.get_field(field_name)
    except Exception:
        return False

    internal_type = getattr(field, "get_internal_type", lambda: "")()
    return internal_type in {"CharField", "EmailField", "TextField"}


def get_registration_payload(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Accept only public creation fields, never arbitrary user-model attributes."""
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

    optional_fields = {"email", "first_name", "last_name"}
    allowed_fields = set(required_fields) | optional_fields
    protected_fields = {
        "pk", "id", user_model._meta.pk.name, user_model._meta.pk.attname,
        "is_staff", "is_superuser", "is_active", "groups", "user_permissions",
        "last_login", "date_joined", "password",
    }
    if set(required_fields) & protected_fields:
        raise ValidationError("Public registration includes a server-managed field.")
    input_fields = allowed_fields | {
        "password", "passwordConfirm", "password_confirmation", "identifier",
    }
    if set(data) - input_fields:
        raise ValidationError("Unsupported registration fields.")
    for field_name in optional_fields:
        if field_name not in registration_data and field_name in data and hasattr(user_model, field_name):
            registration_data[field_name] = data[field_name]

    return registration_data, missing_fields


def find_existing_unique_field(field_name: str, value: Any):
    user_model = get_user_model()
    try:
        field = user_model._meta.get_field(field_name)
    except Exception:
        return None

    if not getattr(field, "unique", False):
        return None

    lookup = (
        {f"{field_name}__iexact": value}
        if isinstance(value, str) and uses_case_insensitive_lookup(field_name)
        else {field_name: value}
    )
    return user_model._default_manager.filter(**lookup).first()


def get_login_credentials(data: dict) -> dict[str, object]:
    session_settings = session_auth_settings()
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
