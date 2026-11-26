"""Topics that organize tutorials for learners."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.definition import ApiSettings, BloomerpModelConfig
from bloomerp.modules.misc import MiscModule


class TutorialTopic(BloomerpModel):
    """Group related tutorials under an ordered catalog heading."""

    class Meta(BloomerpModel.Meta):
        db_table = "bloomerp_tutorial_topic"
        ordering = ("sequence", "name", "pk")

    bloomerp_config = BloomerpModelConfig(
        module=MiscModule,
        description="A topic that groups related tutorials",
        api_settings=ApiSettings(enable_auto_generation=False),
    )

    name = models.CharField(max_length=255, verbose_name=_("Name"))
    source_key = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        editable=False,
        verbose_name=_("Source key"),
        help_text=_("Namespaced key for a topic supplied by an installed app."),
    )
    description = models.TextField(blank=True, verbose_name=_("Description"))
    sequence = models.PositiveIntegerField(default=0, verbose_name=_("Display order"))

    def __str__(self) -> str:
        """Return the name shown to authors and learners."""
        return self.name
