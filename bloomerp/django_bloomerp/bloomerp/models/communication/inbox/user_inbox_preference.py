from django.utils.translation import gettext_lazy as _
from bloomerp.models import BloomerpModel
from bloomerp.models.definition import ActivityLogSettings, BloomerpModelConfig
from bloomerp.models.users.user import AbstractBloomerpUser
from django.db import models
from django.conf import settings


class UserInboxPreference(BloomerpModel):
    class Meta:
        verbose_name = _("User Inbox Preference")
        verbose_name_plural = _("User Inbox Preferences")

    bloomerp_config = BloomerpModelConfig(
        module="communication",
        activity_log_settings=ActivityLogSettings(enabled=False),
        is_internal=True,
    )

    user = models.OneToOneField(
        to=settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="inbox_preference",
        verbose_name=_("User"),
    )
    selected_inbox_folder = models.ForeignKey(
        to="InboxFolder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users_with_selected_inbox_folder_preference",
        verbose_name=_("Selected Inbox Folder"),
    )

    @classmethod
    def get_for_user(cls, user: AbstractBloomerpUser) -> "UserInboxPreference":
        preference, _ = cls.objects.get_or_create(user=user)
        return preference
