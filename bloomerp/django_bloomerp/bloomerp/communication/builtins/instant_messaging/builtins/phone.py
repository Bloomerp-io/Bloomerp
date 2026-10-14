"""Built-in phone directory and carrier-backed conversation operations."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING
from uuid import UUID
from django.apps import apps
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.model_fields.phone_number_field import PhoneNumberField
from bloomerp.permissions.manager import UserPolicyManager, field_access_annotation_name
from bloomerp.models.application_field import ApplicationField
from bloomerp.communication.builtins.voip.access import VoIPAccessManager
from ..definition import (
    BaseIMAdapter,
    IMCapabilities,
    IMConnectionValidation,
    IMConversationActions,
    IMDeliveryResult,
    IMOutboundMessage,
    IMProviderDefinition,
    IMSelectionOption,
    IMSelectionPage,
    IMSelectionStep,
    IMTimelineSource,
)

if TYPE_CHECKING:
    from bloomerp.models.communication.instant_messaging import (
        IMConversation,
        IMIdentity,
        IMMessage,
    )
    from bloomerp.models.communication.voip import PhoneCall


def source_recipient(user: AbstractBloomerpUser, token: str) -> tuple[Any, str, str]:
    """Recheck signed source provenance, row visibility and phone-field permission."""
    try:
        data = signing.loads(token, salt="im-phone-recipient", max_age=3600)
        model = apps.get_model(data["model"])
        field = model._meta.get_field(data["field"])
        if not isinstance(field, PhoneNumberField):
            raise ValueError
        manager = UserPolicyManager(user)
        obj = (
            manager.get_accessible_queryset(model, "view").filter(pk=data["pk"]).first()
        )
        if obj is None:
            raise PermissionDenied
        if (
            not user.is_superuser
            and not manager.get_accessible_fields_for_object(obj, "view")
            .filter(field=field.name)
            .exists()
        ):
            raise PermissionDenied
        address = str(getattr(obj, field.name) or "")
        if address != data["address"] or not address.startswith("+"):
            raise ValidationError(
                _("The phone number has changed. Select the recipient again.")
            )
        return obj, field.name, address
    except (
        signing.BadSignature,
        LookupError,
        ValueError,
        KeyError,
        TypeError,
    ) as error:
        raise ValidationError(_("Select an available phone recipient.")) from error


def phone_recipients(
    user: AbstractBloomerpUser, selected: dict[str, str], query: str, value: str
) -> IMSelectionPage:
    """Search readable phone fields and label recipients using their object's string."""
    if not user.is_authenticated or not user.is_active or not user.is_staff:
        return IMSelectionPage()
    if value:
        obj, field, address = source_recipient(user, value)
        return IMSelectionPage((IMSelectionOption(value, str(obj), address),))
    manager = UserPolicyManager(user)
    results: list[IMSelectionOption] = []
    offset = int(selected.get("_cursor", "0"))
    if offset < 0:
        raise ValueError("Invalid recipient cursor")
    matched = 0
    for model in apps.get_models():
        phone_fields = [
            f for f in model._meta.fields if isinstance(f, PhoneNumberField)
        ]
        if not phone_fields:
            continue
        metadata = list(
            ApplicationField.objects.filter(
                content_type=ContentType.objects.get_for_model(model),
                field__in=[f.name for f in phone_fields],
            )
        )
        field_metadata = {f.field: f for f in metadata}
        queryset = manager.annotate_field_permissions(
            manager.get_accessible_queryset(model, "view"), metadata, "view"
        )
        for obj in queryset.order_by("pk").iterator(chunk_size=100):
            readable = (
                None
                if user.is_superuser
                else {
                    name
                    for name, meta in field_metadata.items()
                    if getattr(obj, field_access_annotation_name(meta), False)
                }
            )
            for field in phone_fields:
                if readable is not None and field.name not in readable:
                    continue
                address = str(getattr(obj, field.name) or "")
                label = str(obj)
                if not address.startswith("+") or (
                    query and query.casefold() not in f"{label} {address}".casefold()
                ):
                    continue
                matched += 1
                if matched <= offset:
                    continue
                token = signing.dumps(
                    {
                        "model": model._meta.label,
                        "pk": str(obj.pk),
                        "field": field.name,
                        "address": address,
                    },
                    salt="im-phone-recipient",
                    compress=True,
                )
                results.append(
                    IMSelectionOption(token, label, f"{field.verbose_name} · {address}")
                )
                if len(results) == 51:
                    return IMSelectionPage(tuple(results[:50]), str(offset + 50))
    return IMSelectionPage(tuple(results))


def business_numbers(
    user: AbstractBloomerpUser, selected: dict[str, str], query: str, value: str
) -> IMSelectionPage:
    """Offer authorized active carrier lines as the provider's second selection."""
    numbers = VoIPAccessManager(user).get_numbers().select_related("connection")
    if value:
        numbers = numbers.filter(pk=value)
    return IMSelectionPage(
        tuple(
            IMSelectionOption(str(n.pk), str(n), n.connection.name)
            for n in numbers.order_by("number")
        )
    )


@transaction.atomic
def start_phone(user: AbstractBloomerpUser, selected: dict[str, str]) -> IMConversation:
    """Create or reuse a line/address chat and enroll its active assigned staff."""
    from bloomerp.models.communication.instant_messaging import (
        IMConversation,
        IMConversationParticipant,
        IMIdentity,
        IMIdentitySource,
    )

    obj, field, address = source_recipient(user, selected["recipient_id"])
    number = (
        VoIPAccessManager(user)
        .get_numbers()
        .select_for_update()
        .filter(pk=selected["number_id"])
        .first()
    )
    if number is None:
        raise PermissionDenied
    identity, _created = IMIdentity.objects.get_or_create(
        connection=None,
        provider_key="phone",
        external_id=address,
        defaults={"display_name": address, "address": address},
    )
    IMIdentitySource.objects.get_or_create(
        identity=identity,
        content_type=ContentType.objects.get_for_model(obj),
        object_id=str(obj.pk),
        field_name=field,
    )
    chat, _created = IMConversation.objects.get_or_create(
        provider_key="phone", voip_number=number, phone_address=address
    )
    IMConversationParticipant.objects.get_or_create(
        conversation=chat, identity=identity
    )
    for assignee in number.assigned_users.filter(is_active=True, is_staff=True):
        IMConversationParticipant.objects.update_or_create(
            conversation=chat, user=assignee, defaults={"left_at": None}
        )
    IMConversationParticipant.objects.update_or_create(
        conversation=chat, user=user, defaults={"left_at": None}
    )
    return chat


def phone_actions(
    user: AbstractBloomerpUser, chat: IMConversation
) -> IMConversationActions:
    """Resolve current line capabilities without making provider HTTP requests."""
    number = (
        VoIPAccessManager(user)
        .get_numbers()
        .select_related("connection")
        .filter(pk=chat.voip_number_id)
        .first()
    )
    if number is None or chat.status == "archived":
        return {"can_send": False}
    browser = number.connection.settings.get("browser_calling", False)
    return {
        "can_send": number.supports_sms,
        "can_call": number.supports_voice and browser,
        "business_number": str(number),
    }


def call_timeline(user: AbstractBloomerpUser, chat: IMConversation) -> list[PhoneCall]:
    """Project authorized call records into the shared conversation timeline."""
    return list(
        VoIPAccessManager(user)
        .get_calls()
        .filter(conversation=chat, parent_call_id="")
        .order_by("datetime_created")
    )


def send_phone_message(
    user: AbstractBloomerpUser,
    conversation_id: UUID,
    html: str,
    client_id: str,
    **kwargs: Any,
) -> IMMessage:
    """Delegate text submission to the telephony service with line authorization."""
    from bloomerp.communication.builtins.voip.controller import VoIPController

    return VoIPController(user).send_message(conversation_id, html, client_id, **kwargs)


class PhoneAdapter(BaseIMAdapter):
    """Describe a built-in directory whose transport is selected per conversation."""

    provider_key = "phone"

    def validate_connection(self) -> IMConnectionValidation:
        """Expose directory availability without creating an IM connection."""
        return IMConnectionValidation(True, IMCapabilities(manual_address=False))

    def send_message(self, message: IMOutboundMessage) -> IMDeliveryResult:
        """Require the authorized line-aware service for carrier delivery."""
        raise NotImplementedError("Use the phone conversation send handler")


def phone_identity_label(identity: IMIdentity, user_id: int | UUID) -> str:
    """Resolve source labels per viewer without leaking another user's CRM visibility."""
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(pk=user_id)
    manager = UserPolicyManager(user)
    for source in identity.sources.select_related("content_type"):
        model = source.content_type.model_class()
        if model is None:
            continue
        obj = (
            manager.get_accessible_queryset(model, "view")
            .filter(pk=source.object_id)
            .first()
        )
        if obj is None:
            continue
        if (
            not user.is_superuser
            and not manager.get_accessible_fields_for_object(obj, "view")
            .filter(field=source.field_name)
            .exists()
        ):
            continue
        if str(getattr(obj, source.field_name, "")) == identity.address:
            return str(obj)
    return identity.address


PHONE_IM_PROVIDER = IMProviderDefinition(
    key="phone",
    display_name=_("Phone"),
    icon="fa-solid fa-phone",
    address_field="phone",
    adapter_class=PhoneAdapter,
    internal=True,
    transport_ready=True,
    selection_steps=(
        IMSelectionStep(
            "recipient_id",
            _("Phone recipients"),
            phone_recipients,
            searchable=True,
        ),
        IMSelectionStep(
            "number_id",
            _("Business number"),
            business_numbers,
        ),
    ),
    start_handler=start_phone,
    send_handler=send_phone_message,
    actions_resolver=phone_actions,
    identity_label_resolver=phone_identity_label,
    timeline_sources=(
        IMTimelineSource(
            call_timeline,
            "components/communication/voip/call_card.html",
        ),
    ),
)
