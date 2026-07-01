from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext as _

from bloomerp.models.base_bloomerp_model import BloomerpModel, FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.definition import BloomerpModelConfig


class InitiativeStatus(models.TextChoices):
    BACKLOG = ("backlog", "Backlog")
    IN_PROGRESS = ("in_progress", "In Progress")
    ON_HOLD = ("on_hold", "On Hold")
    COMPLETED = ("completed", "Completed")
    CANCELED = ("canceled", "Canceled")


class Initiative(BloomerpModel):
    """
    Project-management initiative that groups related to-dos.
    """

    bloomerp_config = BloomerpModelConfig(
        module="misc",
        layout=FieldLayout(
            rows=[
                LayoutRow(
                    title="Details",
                    columns=4,
                    items=[
                        LayoutItem(id="name", colspan=2),
                        LayoutItem(id="status", colspan=1),
                        LayoutItem(id="owner", colspan=1),
                        LayoutItem(id="description", colspan=4),
                    ],
                ),
                LayoutRow(
                    title="Timeline",
                    columns=3,
                    items=[
                        LayoutItem(id="start_date", colspan=1),
                        LayoutItem(id="target_date", colspan=1),
                        LayoutItem(id="completed_at", colspan=1),
                    ],
                ),
                LayoutRow(
                    title="Labels",
                    columns=1,
                    items=[
                        LayoutItem(id="labels", colspan=1),
                    ],
                ),
            ]
        ),
        string_search_fields=["name", "description"],
    )

    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = "bloomerp_initiative"

    avatar = None

    status = models.CharField(
        max_length=20,
        choices=InitiativeStatus.choices,
        default=InitiativeStatus.BACKLOG,
    )
    name = models.CharField(max_length=255, help_text=_("The name of the initiative"))
    description = models.TextField(blank=True, null=True)
    start_date = models.DateField(blank=True, null=True)
    target_date = models.DateField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="owned_initiatives",
    )
    labels = models.ManyToManyField(
        "bloomerp.TodoLabel",
        blank=True,
        related_name="initiatives",
        help_text=_("Labels assigned to the initiative"),
    )

    @property
    def todo_count(self) -> int:
        """Return the number of to-dos assigned to this initiative."""
        return self.todos.count()

    @property
    def is_completed(self) -> bool:
        """Return whether this initiative is marked completed."""
        return self.status == InitiativeStatus.COMPLETED

    def clean(self):
        if self.is_completed and not self.completed_at:
            self.completed_at = timezone.now()
        elif not self.is_completed:
            self.completed_at = None

        return super().clean()

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name
