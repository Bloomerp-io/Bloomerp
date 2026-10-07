"""Validated mailbox presentation and roles for an email account."""

from typing import Any

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    ValidationError as SchemaError,
    model_validator,
)


class MailboxSettings(BaseModel):
    """Describe a provider mailbox without changing its server-side name."""

    model_config = ConfigDict(extra="forbid", strict=True)
    label: str = Field(min_length=1, max_length=255)
    sent_folder: bool = False
    main_folder: bool = False
    color: str = Field(default="", pattern=r"^(#[0-9a-fA-F]{6})?$")


class MailboxMapping(RootModel[dict[str, MailboxSettings]]):
    """Validate mailbox roles and reject ambiguous default destinations."""

    @model_validator(mode="after")
    def validate_roles(self) -> "MailboxMapping":
        """Require named mailboxes and at most one main and one sent folder."""
        if any(not name.strip() for name in self.root):
            raise ValueError("Mailbox names cannot be empty.")
        for role in ("main_folder", "sent_folder"):
            if sum(getattr(settings, role) for settings in self.root.values()) > 1:
                raise ValueError(f"Choose at most one {role.replace('_', ' ')}.")
        return self


def default_mailbox_mapping(names: list[str]) -> dict[str, dict[str, Any]]:
    """Create labels and conservative main/sent defaults for discovered folders."""
    main = next((name for name in names if name.casefold() == "inbox"), None)
    main = main or next((name for name in names if "inbox" in name.casefold()), None)
    sent = next(
        (
            name
            for name in names
            if name.casefold() in {"sent", "sent items", "sent mail"}
        ),
        None,
    )
    sent = sent or next((name for name in names if "sent" in name.casefold()), None)
    return {
        name: MailboxSettings(
            label=name, main_folder=name == main, sent_folder=name == sent
        ).model_dump()
        for name in names
    }


def normalize_mailboxes(value: Any) -> dict[str, dict[str, Any]]:
    """Normalize legacy lists and validate mailbox configuration for persistence."""
    if isinstance(value, list) and all(isinstance(name, str) for name in value):
        value = default_mailbox_mapping(value)
    try:
        return MailboxMapping.model_validate(value).model_dump()
    except SchemaError as exc:
        raise ValidationError(
            _("Invalid mailbox mapping: %(error)s"), params={"error": str(exc)}
        ) from exc


def validate_mailboxes(value: Any) -> None:
    """Expose the mailbox schema as a Django field validator."""
    normalize_mailboxes(value)


def merge_mailboxes(names: list[str], existing: Any) -> dict[str, dict[str, Any]]:
    """Refresh discovered folders while preserving labels, colors and chosen roles."""
    previous = normalize_mailboxes(existing)
    defaults = default_mailbox_mapping(names)
    for role in ("main_folder", "sent_folder"):
        if any(settings[role] for settings in previous.values()):
            for settings in defaults.values():
                settings[role] = False
    return {name: previous.get(name, settings) for name, settings in defaults.items()}
