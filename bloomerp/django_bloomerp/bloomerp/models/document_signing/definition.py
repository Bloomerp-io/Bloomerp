"""Shared field vocabulary and validators for native document signing."""

from dataclasses import dataclass
from enum import Enum
from math import hypot, isfinite
from typing import Literal, TypedDict
from uuid import UUID

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

from bloomerp.models.files.file_node import FileNode


class DrawnSignature(TypedDict):
    """Retain bounded, normalized pen strokes independently of the display resolution."""

    type: Literal["drawn"]
    version: Literal[1]
    strokes: list[list[list[float]]]


def validate_drawn_signature(value: object) -> DrawnSignature:
    """Require visible handwriting represented by finite points inside a 1000 by 300 pad."""
    message = _("Draw your signature using a mouse, touch or pen.")
    if (
        not isinstance(value, dict)
        or value.get("type") != "drawn"
        or type(value.get("version")) is not int
        or value["version"] != 1
    ):
        raise ValidationError(message)
    strokes = value.get("strokes")
    if not isinstance(strokes, list) or not 1 <= len(strokes) <= 100:
        raise ValidationError(message)
    normalized: list[list[list[float]]] = []
    count = 0
    length = 0.0
    left, right, top, bottom = 1.0, 0.0, 1.0, 0.0
    for stroke in strokes:
        if not isinstance(stroke, list) or len(stroke) < 2:
            raise ValidationError(message)
        count += len(stroke)
        if count > 10000:
            raise ValidationError(
                _("The drawing is too detailed. Clear it and try again.")
            )
        points: list[list[float]] = []
        for point in stroke:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise ValidationError(message)
            if any(
                isinstance(number, bool)
                or not isinstance(number, (int, float))
                or not 0 <= number <= 1
                or not isfinite(number)
                for number in point
            ):
                raise ValidationError(message)
            position = [round(float(number), 6) for number in point]
            left, right = min(left, position[0]), max(right, position[0])
            top, bottom = min(top, position[1]), max(bottom, position[1])
            if points:
                length += hypot(
                    position[0] - points[-1][0], (position[1] - points[-1][1]) * 0.3
                )
            points.append(position)
        normalized.append(points)
    if length < 0.02 or max(right - left, (bottom - top) * 0.3) < 0.01:
        raise ValidationError(message)
    return {"type": "drawn", "version": 1, "strokes": normalized}


@dataclass(frozen=True)
class SignatureFieldTypeDefinition:
    """Describe a builder input, its presentation, and its initial PDF geometry."""

    key: str
    label: str | Promise
    icon: str
    description: str | Promise
    width: float = 0.22
    height: float = 0.04
    supports_options: bool = False

    def as_payload(self) -> dict[str, object]:
        """Expose the same field catalog to templates and the TypeScript builder."""
        return {
            "key": self.key,
            "label": str(self.label),
            "icon": self.icon,
            "description": str(self.description),
            "width": self.width,
            "height": self.height,
            "supportsOptions": self.supports_options,
        }


class SignatureFieldTypes(Enum):
    """Provide the rich field catalog using the analytics tile definition pattern."""

    SIGNATURE = SignatureFieldTypeDefinition(
        "signature",
        _("Signature"),
        "fa-solid fa-signature",
        _("Place the signer's signature."),
        height=0.07,
    )
    INITIALS = SignatureFieldTypeDefinition(
        "initials",
        _("Initials"),
        "fa-solid fa-pen-nib",
        _("Ask for the signer's initials."),
        width=0.12,
        height=0.055,
    )
    NAME = SignatureFieldTypeDefinition(
        "name",
        _("Name"),
        "fa-regular fa-user",
        _("The signer's full name."),
    )
    EMAIL = SignatureFieldTypeDefinition(
        "email",
        _("Email"),
        "fa-regular fa-envelope",
        _("An email address."),
        width=0.28,
    )
    PHONE = SignatureFieldTypeDefinition(
        "phone",
        _("Phone"),
        "fa-solid fa-phone",
        _("A telephone number."),
    )
    COMPANY = SignatureFieldTypeDefinition(
        "company",
        _("Company"),
        "fa-regular fa-building",
        _("A company or organization name."),
    )
    TEXT = SignatureFieldTypeDefinition(
        "text",
        _("Text"),
        "fa-solid fa-font",
        _("A single line of text."),
    )
    MULTILINE_TEXT = SignatureFieldTypeDefinition(
        "multiline_text",
        _("Multiline text"),
        "fa-solid fa-align-left",
        _("Several lines of text."),
        width=0.3,
        height=0.1,
    )
    CHECKBOX = SignatureFieldTypeDefinition(
        "checkbox",
        _("Checkbox"),
        "fa-regular fa-square-check",
        _("An independent checkbox."),
        width=0.035,
        height=0.025,
    )
    RADIO = SignatureFieldTypeDefinition(
        "radio",
        _("Radio buttons"),
        "fa-regular fa-circle-dot",
        _("Choose one of several options."),
        height=0.08,
        supports_options=True,
    )
    SELECTION = SignatureFieldTypeDefinition(
        "selection",
        _("Selection"),
        "fa-solid fa-list-ul",
        _("Choose a value from a list."),
        supports_options=True,
    )
    DATE = SignatureFieldTypeDefinition(
        "date",
        _("Date"),
        "fa-regular fa-calendar",
        _("A calendar date."),
        width=0.18,
    )


# Retain the existing string constants while deriving database choices from one catalog.
SignatureFieldType = models.TextChoices(
    "SignatureFieldType",
    {item.name: (item.value.key, item.value.label) for item in SignatureFieldTypes},
)


sha256_validator = RegexValidator(
    regex=r"\A[0-9a-f]{64}\Z", message=_("Enter a lowercase SHA-256 digest.")
)


def validate_file_node(
    file_id: UUID | None, field_name: str, database: str | None
) -> None:
    """Require file references to identify stored files rather than folders."""
    if (
        file_id is not None
        and not FileNode.objects.using(database)
        .filter(pk=file_id, kind=FileNode.FileNodeKind.FILE)
        .exists()
    ):
        raise ValidationError({field_name: _("Select a stored file, not a folder.")})


def validate_json_object(value: object) -> None:
    """Require extensible settings and evidence payloads to be JSON objects."""
    if not isinstance(value, dict):
        raise ValidationError(_("Enter a JSON object."))
