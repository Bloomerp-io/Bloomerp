"""Ordered instructions and interface targets for tutorial revisions."""

from typing import Any, ClassVar

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.definition import ApiSettings, BloomerpModelConfig, SearchSettings

TUTORIAL_STEP_CONFIG = BloomerpModelConfig(
    is_internal=True,
    api_settings=ApiSettings(enable_auto_generation=False),
    string_search_settings=SearchSettings(
        allow_global_search=False, include_search_routes=False
    ),
)

TUTORIAL_STEP_CONTENT_FIELDS = (
    "name",
    "text",
    "size",
    "destination_route",
    "destination_kwargs",
    "interaction",
    "show_as_tooltip",
    "include_backdrop",
    "advance_mode",
    "advance_delay_ms",
    "advance_url_pattern",
    "hide_next_button",
    "is_optional",
)


def empty_tutorial_step_interaction() -> dict[str, Any]:
    """Return a new interaction configuration for a step with no highlights or actions."""
    return {
        "highlights": [],
        "tooltip_highlight_id": "",
        "advance_highlight_id": "",
        "before": [],
        "after": [],
    }


class TutorialStep(BloomerpModel):
    """Guide the learner through one instruction in a tutorial revision."""

    class Size(models.TextChoices):
        """Available widths for the step's presentation card."""

        SMALL = "small", _("Small")
        MEDIUM = "medium", _("Medium")
        LARGE = "large", _("Large")

    class AdvanceMode(models.TextChoices):
        """Conditions that advance the tutorial from this step."""

        MANUAL = "manual", _("Manually")
        CLICK = "click", _("When clicked")
        DOUBLE_CLICK = "dblclick", _("When double-clicked")
        INPUT = "input", _("When typing in an input")
        NAVIGATION = "navigation", _("When navigated to a new URL")
        DELAY = "delay", _("After a delay")

    class Meta(BloomerpModel.Meta):
        db_table = "bloomerp_tutorial_step"
        ordering = ("sequence",)
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("revision", "sequence"),
                name="tutorial_step_unique_sequence",
            ),
            models.UniqueConstraint(
                fields=("revision", "key"),
                name="tutorial_step_unique_key",
            ),
        ]

    bloomerp_config = TUTORIAL_STEP_CONFIG

    revision = models.ForeignKey(
        "bloomerp.TutorialRevision",
        on_delete=models.CASCADE,
        related_name="steps",
        verbose_name=_("Revision"),
    )
    sequence = models.PositiveIntegerField(verbose_name=_("Sequence"))
    key = models.SlugField(max_length=100, db_index=False, verbose_name=_("Step key"))
    name = models.CharField(max_length=255, verbose_name=_("Name"))
    text = models.TextField(blank=True, verbose_name=_("Instructional text"))
    size = models.CharField(
        max_length=6, choices=Size.choices, default=Size.SMALL, verbose_name=_("Size")
    )
    destination_route = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Destination route"),
        help_text=_("Django URL name for the page to open before showing this step."),
    )
    destination_kwargs = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Destination route parameters"),
    )
    interaction = models.JSONField(
        default=empty_tutorial_step_interaction,
        blank=True,
        verbose_name=_("Step interaction"),
    )
    show_as_tooltip = models.BooleanField(default=False, verbose_name=_("Show as tooltip"))
    include_backdrop = models.BooleanField(
        default=True, verbose_name=_("Include backdrop")
    )
    advance_mode = models.CharField(
        max_length=10,
        choices=AdvanceMode.choices,
        default=AdvanceMode.MANUAL,
        verbose_name=_("Advance when"),
    )
    advance_delay_ms = models.PositiveIntegerField(
        default=0, verbose_name=_("Advance delay (ms)")
    )
    advance_url_pattern = models.CharField(
        max_length=2048,
        blank=True,
        verbose_name=_("Advance URL pattern"),
        help_text=_("A local path pattern that triggers navigation-based advancement."),
    )
    hide_next_button = models.BooleanField(default=False, verbose_name=_("Hide Next button"))
    is_optional = models.BooleanField(default=False, verbose_name=_("Optional"))

    def clean(self) -> None:
        """Require keyword arguments suitable for reversing a named Django route."""
        super().clean()
        if not isinstance(self.destination_kwargs, dict) or any(
            not isinstance(key, str) or type(value) not in (str, int)
            for key, value in self.destination_kwargs.items()
        ):
            raise ValidationError(
                {
                    "destination_kwargs": _(
                        "Enter an object with text or integer values."
                    )
                }
            )
        if self.destination_kwargs and not self.destination_route:
            raise ValidationError(
                {"destination_route": _("Choose a destination for these parameters.")}
            )

    def __str__(self) -> str:
        """Return the step's display name."""
        return self.name
