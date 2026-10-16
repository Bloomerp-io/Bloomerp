"""Revision tombstones for cancellations that arrive before their invitations."""

from typing import ClassVar

from django.db import models

from bloomerp.models.definition import (
    ApiSettings,
    BloomerpModelConfig,
    DetailViewSettings,
    ModelViewSettings,
    StringSearchSettings,
)

from .base import CalendarModel


class CalendarSchedulingCancellation(CalendarModel):
    """Keep whole-event or attendee cancellation revisions without creating meetings."""

    bloomerp_config = BloomerpModelConfig(
        module="communication",
        is_internal=True,
        api_settings=ApiSettings(enable_auto_generation=False),
        model_view_settings=ModelViewSettings(
            skip_views=["model", "add", "bulk_upload"]
        ),
        detail_view_settings=DetailViewSettings(
            skip_views=[
                "overview",
                "delete",
                "files",
                "todos",
                "document_templates",
                "create_user_for_object",
                "access_control",
                "foreign_relationship",
            ]
        ),
        string_search_settings=StringSearchSettings(allow_global_search=False),
    )
    calendar_uid = models.CharField(max_length=255)
    organizer_email = models.EmailField()
    attendee_email = models.EmailField(blank=True)
    sequence = models.PositiveIntegerField()
    dtstamp = models.DateTimeField()

    class Meta(CalendarModel.Meta):
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["calendar_uid", "organizer_email", "attendee_email"],
                name="calendar_cancellation_identity_unique",
            ),
        ]

    def __str__(self) -> str:
        """Identify a retained cancellation without needing an event row."""
        return self.calendar_uid
