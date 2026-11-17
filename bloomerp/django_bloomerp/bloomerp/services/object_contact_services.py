"""Resolve readable contact fields for object actions."""

from functools import cached_property
from typing import Any
from urllib.parse import urlencode

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import models
from django.http import HttpRequest
from django.urls import reverse

from bloomerp.communication.builtins.instant_messaging.builtins.phone import phone_recipient_token
from bloomerp.communication.builtins.voip.access import VoIPAccessManager
from bloomerp.form_fields.phone_number_field import normalize_phone_number
from bloomerp.forms.communication.calendar_event import can_create_calendar_event
from bloomerp.model_fields.phone_number_field import PhoneNumberField
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import ObjectActionContext
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.access_tokens import permission_token_url
from bloomerp.permissions.manager import UserPolicyManager, field_access_annotation_name


def contact_fields(model: type[models.Model]) -> list[models.Field]:
    """Discover direct email and phone fields without querying the database."""
    return [
        field for field in model._meta.fields
        if isinstance(field, (models.EmailField, PhoneNumberField))
    ]


class ObjectContactAccess:
    """Reuse contact metadata and communication permissions within a request."""

    def __init__(self, user: AbstractBloomerpUser) -> None:
        """Store the user and their policy manager for contact lookups."""
        self.user = user
        self.permissions = UserPolicyManager(user)
        self._fields: dict[type[models.Model], list[ApplicationField]] = {}

    @cached_property
    def can_open_phone_chat(self) -> bool:
        """Require an eligible staff user with an accessible business line."""
        user = self.user
        return bool(
            user.is_authenticated and user.is_active and user.is_staff
            and VoIPAccessManager(user).get_numbers().exists()
        )

    def fields_for(self, model: type[models.Model]) -> list[ApplicationField]:
        """Return registered contact fields for a globally readable model."""
        if model not in self._fields:
            names = [field.name for field in contact_fields(model)]
            self._fields[model] = list(ApplicationField.objects.filter(
                content_type=ContentType.objects.get_for_model(model), field__in=names,
            )) if names and self.permissions.has_global_permission(model, "view") else []
        return self._fields[model]

    def readable_fields(self, obj: models.Model) -> set[str]:
        """Read dataview annotations or resolve row and field permissions for a detail object."""
        fields = self.fields_for(obj._meta.model)
        if not fields:
            return set()
        annotations = {field.field: field_access_annotation_name(field) for field in fields}
        if all(hasattr(obj, name) for name in annotations.values()):
            return {field for field, name in annotations.items() if getattr(obj, name)}
        if not self.permissions.has_access_to_object(obj, "view", check_global=False):
            return set()
        return set(self.permissions.get_accessible_fields_for_object(obj, "view").filter(
            field__in=annotations,
        ).values_list("field", flat=True))


def get_object_contact_access(request: HttpRequest) -> ObjectContactAccess:
    """Get the contact access resolver for the current request."""
    access = getattr(request, "_bloomerp_contact_access", None)
    if access is None:
        access = ObjectContactAccess(request.user)
        request._bloomerp_contact_access = access
    return access


def object_contact_context(context: ObjectActionContext) -> dict[str, Any]:
    """Build contact menu items from readable, usable values on the current record."""
    request, obj = context.request, context.object
    access = get_object_contact_access(request)
    readable = access.readable_fields(obj)
    emails, phones = [], []
    for field in contact_fields(obj._meta.model):
        if field.name not in readable:
            continue
        raw_value = str(getattr(obj, field.name) or "")
        value = raw_value.strip()
        if not value:
            continue
        item = {"label": str(field.verbose_name), "value": value}
        try:
            if isinstance(field, models.EmailField):
                validate_email(value)
                query = urlencode({
                    "content_type_id": context.content_type.pk,
                    "object_id": obj.pk,
                    "email_field": field.name,
                })
                emails.append({
                    **item,
                    "query": query,
                    "url": permission_token_url(request, f"{reverse('components_new_email')}?{query}"),
                })
            elif raw_value.startswith("+") and normalize_phone_number(value) and access.can_open_phone_chat:
                phones.append({
                    **item,
                    "recipient_id": phone_recipient_token(obj, field.name, raw_value),
                })
        except ValidationError:
            continue
    calendar = []
    if context.surface == "detail" and emails and can_create_calendar_event(request.user):
        calendar_url = reverse("components_calendar_invite_for_object")
        calendar = [
            {**field, "url": permission_token_url(request, f"{calendar_url}?{field['query']}")}
            for field in emails
        ]
    return {
        "object_email_fields": emails,
        "object_phone_fields": phones,
        "object_calendar_fields": calendar,
    }
