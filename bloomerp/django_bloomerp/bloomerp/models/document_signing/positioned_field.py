"""Shared normalized geometry for reusable and request-specific PDF fields."""

from decimal import Decimal
from typing import ClassVar

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import SigningModel
from .definition import SignatureFieldType, validate_json_object


class PositionedSignatureField(SigningModel):
    """Position a typed input on a PDF page using top-left normalized coordinates."""

    key = models.SlugField(_("Key"), max_length=100)
    field_type = models.CharField(
        _("Field type"), max_length=20, choices=SignatureFieldType.choices
    )
    required = models.BooleanField(_("Required"), default=True)
    page_number = models.PositiveIntegerField(
        _("Page number"), default=1, validators=[MinValueValidator(1)]
    )
    x = models.DecimalField(
        _("Left"),
        max_digits=7,
        decimal_places=6,
        default=Decimal(0),
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    y = models.DecimalField(
        _("Top"),
        max_digits=7,
        decimal_places=6,
        default=Decimal(0),
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    width = models.DecimalField(
        _("Width"),
        max_digits=7,
        decimal_places=6,
        default=Decimal("0.2"),
        validators=[MinValueValidator(Decimal("0.000001")), MaxValueValidator(1)],
    )
    height = models.DecimalField(
        _("Height"),
        max_digits=7,
        decimal_places=6,
        default=Decimal("0.05"),
        validators=[MinValueValidator(Decimal("0.000001")), MaxValueValidator(1)],
    )
    settings = models.JSONField(
        _("Settings"), default=dict, blank=True, validators=[validate_json_object]
    )

    class Meta(SigningModel.Meta):
        abstract = True
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(page_number__gte=1),
                name="%(class)s_page_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(x__gte=0, y__gte=0, width__gt=0, height__gt=0)
                    & models.Q(x__lte=1 - models.F("width"))
                    & models.Q(y__lte=1 - models.F("height"))
                ),
                name="%(class)s_rectangle_valid",
            ),
        ]

    def clean(self) -> None:
        """Reject rectangles that extend outside the rendered PDF page."""
        super().clean()
        try:
            validate_json_object(self.settings)
        except ValidationError as error:
            raise ValidationError({"settings": error.messages}) from error
        for origin, extent in (("x", "width"), ("y", "height")):
            start, size = getattr(self, origin), getattr(self, extent)
            if (
                isinstance(start, Decimal)
                and isinstance(size, Decimal)
                and start + size > 1
            ):
                raise ValidationError(
                    {extent: _("The field must fit inside its page.")}
                )
