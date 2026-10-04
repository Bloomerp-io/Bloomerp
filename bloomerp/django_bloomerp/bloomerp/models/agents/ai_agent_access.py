"""Explicit user and group grants for using an AI agent."""

from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models
from django.utils.translation import gettext_lazy as _

from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.definition import ApiSettings, BloomerpModelConfig
from bloomerp.modules.bloomai import BloomAIModule


class AIAgentAccess(BloomerpModel):
    """Grant agent use without granting configuration or credential access."""

    class Meta(BloomerpModel.Meta):
        db_table = "bloomerp_ai_agent_access"
        verbose_name = _("AI Agent Access")
        verbose_name_plural = _("AI Agent Access")

    bloomerp_config = BloomerpModelConfig(
        module=BloomAIModule,
        api_settings=ApiSettings(enable_auto_generation=False),
    )
    avatar = None
    name = models.CharField(max_length=255, verbose_name=_("Name"))
    model = models.ForeignKey(
        "bloomerp.AIAgent",
        on_delete=models.CASCADE,
        related_name="access",
        verbose_name=_("AI Agent"),
        help_text=_("Agent that these users and groups may use."),
    )
    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="ai_agent_access_grants",
        verbose_name=_("Users"),
        help_text=_("Users who may use this agent."),
    )
    groups = models.ManyToManyField(
        Group,
        blank=True,
        related_name="ai_agent_access_grants",
        verbose_name=_("Groups"),
        help_text=_("Members of these groups may use this agent."),
    )

    def __str__(self) -> str:
        """Return the descriptive name of this access grant."""
        return self.name
