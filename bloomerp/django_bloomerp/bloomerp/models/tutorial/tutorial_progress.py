"""Per-user tutorial progress and reporting milestones."""

from typing import ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.definition import (
    ActivityLogSettings,
    ApiSettings,
    BloomerpModelConfig,
    SearchSettings,
)

from .tutorial_step import TutorialStep

TUTORIAL_PROGRESS_CONFIG = BloomerpModelConfig(
    is_internal=True,
    api_settings=ApiSettings(enable_auto_generation=False),
    string_search_settings=SearchSettings(
        allow_global_search=False, include_search_routes=False
    ),
    activity_log_settings=ActivityLogSettings(enabled=False),
)


class TutorialProgress(BloomerpModel):
    """Track what a user has seen and where they can resume a revision."""

    class Meta(BloomerpModel.Meta):
        db_table = "bloomerp_tutorial_progress"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("revision", "user"), name="tutorial_progress_unique_user"
            ),
        ]

    bloomerp_config = TUTORIAL_PROGRESS_CONFIG

    revision = models.ForeignKey(
        "bloomerp.TutorialRevision",
        on_delete=models.CASCADE,
        related_name="progress_records",
        verbose_name=_("Revision"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tutorial_progress_records",
        verbose_name=_("User"),
    )
    current_step = models.ForeignKey(
        TutorialStep,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="progress_records",
        verbose_name=_("Current step"),
    )
    first_shown_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("First shown at")
    )
    started_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Started at")
    )
    dismissed_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Dismissed at")
    )
    completed_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Completed at")
    )

    def clean(self) -> None:
        """Keep the resume step within the revision tracked by this record."""
        super().clean()
        if self.current_step_id is None or self.revision_id is None:
            return

        try:
            current_step = self.current_step
        except TutorialStep.DoesNotExist:
            return  # The foreign key field validates whether the step exists.
        if current_step.revision_id != self.revision_id:
            raise ValidationError(
                {"current_step": _("Choose a step from this tutorial revision.")}
            )

    def __str__(self) -> str:
        """Display the revision without exposing the learner's identity."""
        return str(self.revision)
