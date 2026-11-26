"""Shared signing, expiry, and validation for BloomERP tokens."""

import json
from datetime import datetime, timedelta
from math import ceil
from secrets import token_hex
from typing import Any, ClassVar, Self

from django.apps import apps
from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import AnonymousUser
from django.core import signing
from django.core.cache import caches
from django.core.exceptions import PermissionDenied
from django.db.models import Model
from django.http import HttpRequest, QueryDict
from django.utils import timezone
from django.utils.crypto import salted_hmac
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    SerializeAsAny,
    field_serializer,
    field_validator,
    model_validator,
)

from bloomerp.dataviews.definition import BaseDataview
from bloomerp.models.definition import DetailTabsConfiguration, FieldLayout
from bloomerp.permissions.definition import AccessRule, BloomerpPermission


class SignedToken(BaseModel):
    """Sign and verify typed claims with a salt specific to each token type."""

    model_config = ConfigDict(extra="forbid")

    signing_salt: ClassVar[str]
    expiry: AwareDatetime

    def sign(self) -> str:
        """Serialize the claims to compressed, signed JSON."""
        payload = self.model_dump(mode="json", by_alias=True, exclude_none=True)
        return signing.dumps(payload, salt=self.signing_salt, compress=True)

    @classmethod
    def verify(cls, token: str) -> Self:
        """Check the signature, payload, and expiry before returning a token."""
        return cls._validate_payload(cls._load_payload(token))

    @classmethod
    def _load_payload(cls, token: str) -> dict[str, Any]:
        """Read claims only after verifying the signature for this token type."""
        try:
            payload = signing.loads(token, salt=cls.signing_salt)
        except (signing.BadSignature, TypeError, ValueError) as error:
            raise PermissionDenied("Invalid token") from error
        if not isinstance(payload, dict):
            raise PermissionDenied("Invalid token payload")
        return payload

    @classmethod
    def _validate_payload(cls, payload: dict[str, Any]) -> Self:
        """Validate the typed claims and require an unexpired token."""
        try:
            verified = cls.model_validate(payload)
        except ValueError as error:
            raise PermissionDenied("Invalid token payload") from error
        if verified.expiry <= timezone.now():
            raise PermissionDenied("Token expired")
        return verified


class ModelScopedToken(SignedToken):
    """Bind a token to a Django model and, when present, a saved user."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    model: type[Model] = Field(serialization_alias="model_label")
    user: AbstractBaseUser | None = Field(default=None, serialization_alias="audience")

    @model_validator(mode="after")
    def validate_saved_user(self) -> Self:
        """Require a saved user when the token specifies a recipient."""
        if self.user is not None and (self.user.pk is None or self.user._state.adding):
            raise ValueError("Supply a saved user")
        return self

    @field_serializer("model", when_used="json")
    def serialize_model(self, model: type[Model]) -> str:
        """Use the canonical Django model label in the signed payload."""
        return model._meta.label_lower

    @field_serializer("user", when_used="json")
    def serialize_user(self, user: AbstractBaseUser | None) -> str | None:
        """Use the recipient's primary key in the signed payload."""
        return str(user.pk) if user is not None else None

    @classmethod
    def verify(
        cls,
        token: str,
        *,
        user: AbstractBaseUser | AnonymousUser | None = None,
        model: type[Model] | None = None,
    ) -> Self:
        """Verify the recipient and bind the claims to their signed model."""
        payload = cls._load_payload(token)
        audience = payload.pop("audience", None)
        if audience is not None and (
            user is None or not user.is_authenticated or user.pk is None or audience != str(user.pk)
        ):
            raise PermissionDenied("Token belongs to another user")

        model_label = payload.pop("model_label", None)
        if not isinstance(model_label, str):
            raise PermissionDenied("Invalid token model")
        if model is None:
            try:
                model = apps.get_model(model_label)
            except (LookupError, ValueError) as error:
                raise PermissionDenied("Invalid token model") from error
        if model._meta.label_lower != model_label:
            raise PermissionDenied("Token belongs to another model")

        return cls._validate_payload(
            {**payload, "model": model, "user": user if audience is not None else None}
        )


class DataviewToken(ModelScopedToken):
    """Carry an inline layout or saved preference reference for a single viewer."""

    signing_salt = "bloomerp.tokens.dataview.v1"

    preference_id: PositiveInt | None = None
    dataview: SerializeAsAny[BaseDataview] | None = None
    object_actions: list[str] | None = None
    dataview_actions: list[str] | None = None
    create_url: str | None = None
    relationship_field: str | None = None
    hide_filters: bool = False

    @field_validator("dataview", mode="before")
    @classmethod
    def validate_dataview(cls, value: object) -> BaseDataview | None:
        """Validate the inline layout against its registered concrete config class."""
        if value is None:
            return None

        from bloomerp.dataviews.registry import DATAVIEW_REGISTRY

        config = value.model_dump() if isinstance(value, BaseDataview) else value
        if not isinstance(config, dict) or not isinstance(view_type := config.get("view_type"), str):
            raise ValueError("Supply a dataview configuration with a view_type")  # noqa: TRY004 - Pydantic reports this as validation.
        definition = DATAVIEW_REGISTRY.get(view_type)
        if definition is None:
            raise ValueError(f"Unknown dataview type: {view_type}")
        return definition.config_cls.model_validate(config)

    @model_validator(mode="after")
    def validate_layout(self) -> Self:
        """Require a viewer and exactly one layout source."""
        if self.user is None:
            raise ValueError("Supply a viewer")
        if (self.preference_id is None) == (self.dataview is None):
            raise ValueError("Supply either preference_id or dataview")
        return self

    @classmethod
    def verify(
        cls,
        token: str,
        *,
        user: AbstractBaseUser | AnonymousUser | None = None,
        model: type[Model] | None = None,
    ) -> Self:
        """Verify a layout against the model requested by the viewer."""
        if model is None:
            raise PermissionDenied("A dataview model is required")
        return super().verify(token, user=user, model=model)


class DetailViewToken(ModelScopedToken):
    """Carry field layout and tab overrides for one signed-in viewer and model."""

    signing_salt = "bloomerp.tokens.detail_view.v1"

    preference_id: PositiveInt | None = None
    field_layout: FieldLayout | None = None
    tab_configuration: DetailTabsConfiguration | None = None
    object_actions: list[str] | None = None
    allow_layout_edit: bool = False

    @property
    def has_layout_override(self) -> bool:
        """Indicate whether the token replaces the viewer's selected field layout."""
        return self.preference_id is not None or self.field_layout is not None

    @model_validator(mode="after")
    def validate_layout(self) -> Self:
        """Require a viewer and an override, and validate the field layout options."""
        if self.user is None:
            raise ValueError("Supply a viewer")
        if self.preference_id is not None and self.field_layout is not None:
            raise ValueError("Supply either preference_id or field_layout")
        if not self.has_layout_override and self.tab_configuration is None:
            raise ValueError("Supply preference_id, field_layout, or tab_configuration")
        if self.allow_layout_edit and self.preference_id is None:
            raise ValueError("Layout editing requires a saved preference")
        return self


def _permission_name(permission: BloomerpPermission | str) -> str:
    """Serialize permission enums as portable codenames."""
    return permission.value.codename if isinstance(permission, BloomerpPermission) else permission


class PermissionToken(ModelScopedToken):
    """Carry a model-scoped access rule issued by trusted server-side code."""

    signing_salt = "bloomerp.tokens.permission.v1"

    rule: AccessRule
    public: bool = False

    @model_validator(mode="after")
    def validate_audience(self) -> Self:
        """Require either a recipient or an explicitly public grant."""
        if self.public == (self.user is not None):
            raise ValueError("Choose either a user or an explicit public token")
        return self

    @field_serializer("rule", when_used="json")
    def serialize_rule(self, rule: AccessRule) -> dict[str, Any]:
        """Encode row and field grants using permission codenames."""
        return {
            "row_permissions": [
                {
                    **row.model_dump(mode="json", exclude={"permissions"}),
                    "permissions": [_permission_name(value) for value in row.permissions],
                }
                for row in rule.row_permissions
            ],
            "field_permissions": {
                field: [_permission_name(value) for value in values]
                for field, values in rule.field_permissions.items()
            },
        }


REQUEST_TOKEN_HEADER = "X-Bloomerp-Context"
REQUEST_TOKEN_QUERY_KEYS = frozenset({
    "_permission_token", "_dataview_token", "_dataview_detail_view_token",
    "_detail_view_token", "_dataview_operation_context",
})


def request_query_params(request: HttpRequest) -> QueryDict:
    """Copy ordinary query parameters and discard obsolete credential keys."""
    query = request.GET.copy()
    for key in REQUEST_TOKEN_QUERY_KEYS:
        query.pop(key, None)
    return query


def request_token_expiry() -> datetime:
    """Return the default expiry for a newly opened context."""
    return timezone.now() + timedelta(hours=1)


class RequestToken(BaseModel):
    """Keep the grants and presentation settings for one opened UI context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    expiry: AwareDatetime = Field(default_factory=request_token_expiry)
    policies: dict[type[Model], AccessRule] = Field(default_factory=dict)
    dataviews: dict[type[Model], DataviewToken] = Field(default_factory=dict)
    detail_views: dict[type[Model], DetailViewToken] = Field(default_factory=dict)
    create_views: dict[type[Model], DetailViewToken] = Field(default_factory=dict)
    operation_preferences: dict[int, int] = Field(default_factory=dict)

    def serialize(self) -> dict[str, Any]:
        """Encode model-scoped settings and policies for the server-side cache."""
        return {
            "expiry": self.expiry.isoformat(),
            "policies": {
                model._meta.label_lower: {
                    "row_permissions": [
                        {
                            **row.model_dump(mode="json", exclude={"permissions"}),
                            "permissions": [_permission_name(value) for value in row.permissions],
                        }
                        for row in rule.row_permissions
                    ],
                    "field_permissions": {
                        name: [_permission_name(value) for value in permissions]
                        for name, permissions in rule.field_permissions.items()
                    },
                }
                for model, rule in self.policies.items()
            },
            "dataviews": {model._meta.label_lower: token.sign() for model, token in self.dataviews.items()},
            "detail_views": {model._meta.label_lower: token.sign() for model, token in self.detail_views.items()},
            "create_views": {model._meta.label_lower: token.sign() for model, token in self.create_views.items()},
            "operation_preferences": self.operation_preferences,
        }

    @classmethod
    def deserialize(cls, claims: dict[str, Any], user: AbstractBaseUser) -> Self:
        """Resolve signed settings for the authenticated viewer and their canonical model labels."""
        return cls.model_validate({
            **claims,
            "policies": {apps.get_model(label): rule for label, rule in claims["policies"].items()},
            "dataviews": _deserialize_view_tokens(claims["dataviews"], DataviewToken, user),
            "detail_views": _deserialize_view_tokens(claims["detail_views"], DetailViewToken, user),
            "create_views": _deserialize_view_tokens(claims.get("create_views", {}), DetailViewToken, user),
        })


def _deserialize_view_tokens[Token: ModelScopedToken](
    claims: dict[str, str], token_type: type[Token], user: AbstractBaseUser,
) -> dict[type[Model], Token]:
    """Restore model classes and check that each cached view belongs to its key."""
    views = {}
    for label, value in claims.items():
        model = apps.get_model(label)
        views[model] = token_type.verify(value, user=user, model=model)
    return views


def _request_token_cache_key(request: HttpRequest, context_id: str) -> str:
    """Bind a stored context to the authenticated session which opened it."""
    session_key = getattr(getattr(request, "session", None), "session_key", None)
    user = request.user
    if not user.is_authenticated or not session_key:
        raise PermissionDenied("Sign in to use this request context.")
    audience = salted_hmac("bloomerp.request-token", f"{user.pk}:{session_key}").hexdigest()
    return f"request-context:{audience}:{context_id}"


def issue_token(token: RequestToken, request: HttpRequest, *, activate: bool = False) -> str:
    """Store a fresh session-bound context and optionally use it for the current rendering."""
    timeout = ceil((token.expiry - timezone.now()).total_seconds())
    if timeout <= 0:
        raise PermissionDenied("Request context expired.")
    context_id = token_hex(16)
    store = caches["request_tokens" if "request_tokens" in settings.CACHES else "default"]
    store.set(_request_token_cache_key(request, context_id), token.serialize(), timeout)
    if activate:
        request._bloomerp_issued_context_id = context_id
        request._bloomerp_request_token = token
    return context_id


def get_token(request: HttpRequest) -> RequestToken | None:
    """Resolve the incoming context once for the current authenticated request."""
    if hasattr(request, "_bloomerp_request_token"):
        return request._bloomerp_request_token
    context_id = request.headers.get(REQUEST_TOKEN_HEADER)
    if context_id is None:
        request._bloomerp_request_token = None
        return None
    if len(context_id) != 32 or any(char not in "0123456789abcdef" for char in context_id):
        raise PermissionDenied("Invalid request context.")
    store = caches["request_tokens" if "request_tokens" in settings.CACHES else "default"]
    claims = store.get(_request_token_cache_key(request, context_id))
    if claims is None:
        raise PermissionDenied("Request context expired or unavailable.")
    token = RequestToken.deserialize(claims, request.user)
    if token.expiry <= timezone.now():
        raise PermissionDenied("Request context expired.")
    request._bloomerp_request_token = token
    return token


def request_token_headers(context_id: str) -> str:
    """Build the HTMX headers for an already-issued context."""
    return json.dumps({REQUEST_TOKEN_HEADER: context_id})


def request_token_id(request: HttpRequest) -> str | None:
    """Find the context ID received by this request or issued during its rendering."""
    return getattr(request, "_bloomerp_issued_context_id", None) or request.headers.get(REQUEST_TOKEN_HEADER)


def request_context_attributes(request: HttpRequest, token: RequestToken) -> dict[str, str]:
    """Issue a context and attach its header to the action that opens it."""
    return {"hx-headers": request_token_headers(issue_token(token, request))}


def get_detail_token(
    request: HttpRequest, model: type[Model], *, create: bool = False,
) -> DetailViewToken | None:
    """Resolve this model's layout for the current detail or create view."""
    context = get_token(request)
    if context is None:
        return None
    views = context.create_views if create else context.detail_views
    return views.get(model)
