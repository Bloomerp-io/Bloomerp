"""Execute provider-defined conversation setup without provider-specific branches."""

from typing import Any
from django.core.exceptions import ValidationError, PermissionDenied
from bloomerp.utils.callables import resolve_hook
from django.utils.translation import gettext as _
from bloomerp.models.users.user import AbstractBloomerpUser
from .definition import (
    IMProviderDefinition,
    IMSelectionOption,
    IMSelectionPage,
    IMSelectionStep,
)


def resolve_steps(
    provider: IMProviderDefinition,
    user: AbstractBloomerpUser,
    submitted: dict[str, str],
    query: str = "",
    cursor: str = "",
) -> tuple[dict[str, str], IMSelectionStep | None, IMSelectionPage]:
    """Revalidate each prerequisite and return the next unresolved selection."""
    selected: dict[str, str] = {"_provider": provider.key}
    for step in provider.selection_steps:
        value = submitted.get(step.key, "")
        if cursor and not value:
            selected["_cursor"] = cursor
        page = resolve_hook(step.resolver)(
            user, selected, "" if value else query, value
        )
        selected.pop("_cursor", None)
        options = page.items
        if value:
            if value not in {option.value for option in options}:
                raise ValidationError(_("This selection is no longer available."))
            selected[step.key] = value
        elif len(options) == 1 and not step.searchable:
            selected[step.key] = options[0].value
        else:
            return selected, step, page
    return selected, None, IMSelectionPage()


def staff_recipients(
    user: AbstractBloomerpUser, selected: dict[str, str], query: str, value: str
) -> IMSelectionPage:
    """Resolve the native directory while validating exact selected staff identities."""
    from django.contrib.auth import get_user_model
    from .controller import IMController

    if value:
        recipient = (
            get_user_model()
            .objects.filter(pk=value, is_active=True, is_staff=True)
            .exclude(pk=user.pk)
            .first()
        )
        if recipient is None:
            raise PermissionDenied
        return IMSelectionPage((IMSelectionOption(str(recipient.pk), str(recipient)),))
    page = IMController(user).discover_recipients(query, selected.get("_cursor"))
    return IMSelectionPage(
        tuple(
            IMSelectionOption(p.external_id, p.display_name, p.address)
            for p in page.items
        ),
        page.next_cursor,
    )


def start_staff(user: AbstractBloomerpUser, selected: dict[str, str]) -> Any:
    """Delegate native persistence to the existing staff conversation controller."""
    from .controller import IMController

    return IMController(user).start_internal_conversation(selected["recipient_id"])


def configured_connections(
    user: AbstractBloomerpUser, selected: dict[str, str], query: str, value: str
) -> IMSelectionPage:
    """Offer authorized configured accounts for the definition's external provider."""
    from bloomerp.permissions.manager import UserPolicyManager
    from bloomerp.models.communication.instant_messaging import IMConnection

    connections = (
        UserPolicyManager(user)
        .get_accessible_queryset(IMConnection, "view")
        .filter(provider=selected["_provider"])
    )
    if value:
        connections = connections.filter(pk=value)
    return IMSelectionPage(
        tuple(
            IMSelectionOption(str(c.pk), c.name, c.get_status_display())
            for c in connections.order_by("name")[:50]
        )
    )


def configured_endpoints(
    user: AbstractBloomerpUser, selected: dict[str, str], query: str, value: str
) -> IMSelectionPage:
    """Resolve an account's authorized sending endpoints after connection selection."""
    from bloomerp.models.communication.instant_messaging import IMEndpoint
    from bloomerp.permissions.manager import UserPolicyManager

    endpoints = (
        UserPolicyManager(user)
        .get_accessible_queryset(IMEndpoint, "view")
        .filter(connection_id=selected["connection_id"], is_active=True)
    )
    if value:
        endpoints = endpoints.filter(pk=value)
    return IMSelectionPage(
        tuple(
            IMSelectionOption(str(e.pk), e.name, e.address)
            for e in endpoints.order_by("name")[:50]
        )
    )


def external_recipients(
    user: AbstractBloomerpUser, selected: dict[str, str], query: str, value: str
) -> IMSelectionPage:
    """Keep draft external transports unavailable until their authorized directory exists."""
    return IMSelectionPage()


def start_external(user: AbstractBloomerpUser, selected: dict[str, str]) -> Any:
    """Reject direct completion while the external provider transport remains a draft."""
    raise ValidationError(
        _("This provider's messaging transport is not available yet.")
    )
