"""Private, expiring state for one mailbox authorization attempt."""

from django.conf import settings
from django.db import models

from bloomerp.models.definition import (
    ActivityLogSettings,
    ApiSettings,
    BloomerpModelConfig,
)


class EmailAuthorizationRequest(models.Model):
    """Bind encrypted setup data to one actor, browser, account and callback origin."""

    bloomerp_config = BloomerpModelConfig(
        is_internal=True,
        api_settings=ApiSettings(enable_auto_generation=False),
        activity_log_settings=ActivityLogSettings(enabled=False),
    )

    state_digest = models.CharField(max_length=64, primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    account = models.ForeignKey(
        "bloomerp.EmailAccount", null=True, on_delete=models.CASCADE
    )
    session_digest = models.CharField(max_length=64)
    redirect_uri = models.URLField(max_length=2048)
    payload = models.TextField()
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        default_permissions = ()
        db_table = "bloomerp_email_authorization_request"
