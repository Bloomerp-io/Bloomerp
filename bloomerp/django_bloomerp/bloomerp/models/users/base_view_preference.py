from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _

from bloomerp.models.definition import BloomerpModelConfig


class BaseViewPreference(models.Model):
    """Shared identity and selection behavior for per-user saved view preferences."""

    class Meta:
        abstract = True

    bloomerp_config = BloomerpModelConfig(
        is_internal=True
    )

    name = models.CharField(
        max_length=255,
        help_text=_("Optional name for this layout preference, for user reference"),
        default="Default",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_preferences",
    )
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
    )
    selected = models.BooleanField(
        default=False,
        help_text=_(
            "Indicates if this preference is currently selected for the user. "
            "Only one preference per user and content type can be selected at a time."
        ),
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
        return cls.objects.filter(
            user=user,
            content_type=content_type,
            selected=True,
        ).first()

    @classmethod
    def get_or_create_for_user(
        cls,
        user,
        content_type_or_model: ContentType | models.Model,
    ) -> "BaseViewPreference":
        content_type = cls.resolve_content_type(content_type_or_model)

        preference = cls.get_selected_for_user(user, content_type)
        if preference is None:
            preference = cls.objects.filter(
                user=user,
                content_type=content_type,
            ).order_by("pk").first()
            if preference is not None:
                preference.select()

        if preference is None:
            preference = cls.create_default_for_user(user, content_type)

        preference.ensure_default_state(user=user, content_type=content_type)
        return preference

    @classmethod
    def create_default_for_user(
        cls,
        user,
        content_type_or_model: ContentType | models.Model,
    ) -> "BaseViewPreference":
        raise NotImplementedError

    def ensure_default_state(self, *, user, content_type: ContentType) -> None:
        """Allow subclasses to repair invalid or empty stored state."""

    def select(self) -> None:
        self.__class__.objects.filter(
            user=self.user,
            content_type=self.content_type,
            selected=True,
        ).exclude(pk=self.pk).update(selected=False)
        if not self.selected:
            self.selected = True
            self.save(update_fields=["selected"])

    def save(self, *args, **kwargs):
        if self.selected and self.user_id and self.content_type_id:
            self.__class__.objects.filter(
                user=self.user,
                content_type=self.content_type,
                selected=True,
            ).exclude(pk=self.pk).update(selected=False)

        super().save(*args, **kwargs)

        selected_qs = self.__class__.objects.filter(
            user=self.user,
            content_type=self.content_type,
            selected=True,
        )

        if self.selected:
            selected_qs.exclude(pk=self.pk).update(selected=False)
            return

        if not selected_qs.exclude(pk=self.pk).exists():
            self.__class__.objects.filter(pk=self.pk).update(selected=True)
            self.selected = True

    def __str__(self):
        return f"{self.name} for {self.user} on {self.content_type}"
    
