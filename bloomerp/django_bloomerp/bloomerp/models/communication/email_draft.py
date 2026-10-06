"""Private composer snapshots, independent from provider-side IMAP drafts."""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from bloomerp.filters.definition import FilterCondition
from bloomerp.permissions.definition import AccessRule, RowPolicyRuleContent
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.definition import ActivityLogSettings, ApiAccessSettings, ApiSettings, BloomerpModelConfig, StringSearchSettings


class EmailDraft(BloomerpModel):
    """Store an owner's editable message and template arguments until sending."""

    bloomerp_config = BloomerpModelConfig(
        is_internal=True,
        activity_log_settings=ActivityLogSettings(enabled=False),
        api_settings=ApiSettings(
            enable_auto_generation=True,
            access=ApiAccessSettings(authenticated=[
                AccessRule(
                    row_permissions=[RowPolicyRuleContent(
                        permissions=["add", "view", "change", "delete"],
                        conditions=[FilterCondition(field_path="user", lookup_id="equals", value="$user")],
                    )],
                    field_permissions={
                        "id": ["add", "view"],
                        "user": ["add", "view"],
                        "email_account": ["add", "view", "change"],
                        "content_type": ["add", "view", "change"],
                        "object_id": ["add", "view", "change"],
                        "payload": ["add", "view", "change"],
                    },
                ),
            ]),
        ),
        string_search_settings=StringSearchSettings(allow_global_search=False)
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    email_account = models.ForeignKey("bloomerp.EmailAccount", on_delete=models.SET_NULL, null=True)
    content_type = models.ForeignKey("contenttypes.ContentType", on_delete=models.SET_NULL, null=True)
    object_id = models.CharField(max_length=255, blank=True)
    payload = models.JSONField(default=dict)

    class Meta:
        db_table = "bloomerp_email_draft"
        verbose_name = _("Email Draft")
        verbose_name_plural = _("Email Drafts")
