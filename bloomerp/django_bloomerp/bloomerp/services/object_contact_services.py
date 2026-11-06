"""Resolve authorized detail actions through the existing communication composers."""

from typing import Any
from urllib.parse import urlencode

from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.urls import reverse

from bloomerp.communication.builtins.instant_messaging.builtins.phone import (
    phone_fields_for_object,
)
from bloomerp.forms.communication.calendar_event import can_create_calendar_event
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.services.email_composer_services import email_fields_for_object


def object_contact_context(user: AbstractBloomerpUser, obj: models.Model) -> dict[str, Any]:
    """Group readable contact fields without bypassing composer or carrier authorization."""
    emails = email_fields_for_object(user, obj)
    calendar_fields = []
    if emails and can_create_calendar_event(user):
        content_type = ContentType.objects.get_for_model(obj)
        for field in emails:
            query = urlencode({
                "content_type_id": content_type.pk,
                "object_id": str(obj.pk),
                "email_field": field["name"],
            })
            calendar_fields.append({
                **field,
                "url": f"{reverse('components_calendar_invite_for_object')}?{query}",
            })
    return {
        "object_email_fields": emails,
        "object_phone_fields": phone_fields_for_object(user, obj),
        "object_calendar_fields": calendar_fields,
    }
