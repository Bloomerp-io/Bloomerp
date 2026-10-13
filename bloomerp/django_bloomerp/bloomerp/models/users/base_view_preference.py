from django.utils.translation import gettext_lazy as _
from django.contrib.contenttypes.models import ContentType
from django.db import models

from bloomerp.models.definition import BloomerpModelConfig
from bloomerp.models.users.base_preference import BasePreference


class BaseViewPreference(BasePreference):
    """Shared identity and selection behavior for per-user saved view preferences."""

    preference_scope_fields = ("content_type",)

    class Meta:
        abstract = True

    bloomerp_config = BloomerpModelConfig(
        is_internal=True,
        api_settings=BasePreference.bloomerp_config.api_settings.model_copy(deep=True),
    )
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        verbose_name=_("Content Type"),
    )

    @classmethod
    def resolve_content_type(
        cls,
        content_type_or_model: ContentType | models.Model,
    ) -> ContentType:
        if isinstance(content_type_or_model, ContentType):
            return content_type_or_model
        return ContentType.objects.get_for_model(content_type_or_model)

    @classmethod
    def get_selected_for_user(
        cls,
        user,
        content_type_or_model: ContentType | models.Model,
    ) -> "BaseViewPreference | None":
        content_type = cls.resolve_content_type(content_type_or_model)
        preference = cls.objects.filter(
            user=user,
            content_type=content_type,
            selected=True,
        ).select_related("source_object").first()
        return preference.effective_preference if preference else None


    def ensure_default_state(self, *, user, content_type: ContentType) -> None:
        """Allow subclasses to repair invalid or empty stored state."""

    def __str__(self):
        return f"{self.name} for {self.user} on {self.content_type}"
