"""Explicit user and group grants for using an AI agent."""

from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop

from bloomerp.dataviews.table.config import TableDataView
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.definition import (
    ApiSettings,
    BloomerpModelConfig,
    DetailViewSettings,
    FieldLayout,
    LayoutItem,
    LayoutRow,
    ModelViewSettings,
)
from bloomerp.modules.bloomai import BloomAIModule


class AIAgentAccess(BloomerpModel):
    """Grant agent use without granting configuration or credential access."""

    class Meta(BloomerpModel.Meta):
        db_table = "bloomerp_ai_agent_access"
        verbose_name = _("AI Agent Access")
        verbose_name_plural = _("AI Agent Access")

    bloomerp_config = BloomerpModelConfig(
        model_view_settings=ModelViewSettings(
            default_dataviews=[
                TableDataView(
                    name=gettext_noop("AI agent access"),
                    display_fields=[
                        "name",
                        "model",
                        "all_staff_users",
                        "all_authenticated_users",
                    ],
                    sort_field="name",
                )
            ]
        ),
        detail_view_settings=DetailViewSettings(
            layouts=[
                FieldLayout(
                    rows=[
                        LayoutRow(
                            columns=2,
                            title=gettext_noop("Access grant"),
                            items=[LayoutItem(id="name"), LayoutItem(id="model")],
                        ),
                        LayoutRow(
                            columns=2,
                            title=gettext_noop("Who can use this agent"),
                            items=[
                                LayoutItem(id="all_staff_users"),
                                LayoutItem(id="all_authenticated_users"),
                                LayoutItem(id="users"),
                                LayoutItem(id="groups"),
                            ],
                        ),
                    ]
                )
            ]
        ),
        module=BloomAIModule,
        api_settings=ApiSettings(enable_auto_generation=False),
    )
    avatar = None
    name = models.CharField(max_length=255, verbose_name=_("Name"))
    all_staff_users = models.BooleanField(
        default=False,
        verbose_name=_("All Staff Users"),
        help_text=_("Allow all active staff users to use this agent."),
    )
    all_authenticated_users = models.BooleanField(
        default=False,
        verbose_name=_("All Authenticated Users"),
        help_text=_("Allow all active authenticated users to use this agent."),
    )
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
