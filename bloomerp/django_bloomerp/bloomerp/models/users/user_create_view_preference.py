from django.contrib.contenttypes.models import ContentType
from django.db import models

from bloomerp.models.base_bloomerp_model import BloomerpModel, FieldLayout
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.services.sectioned_layout_services import normalize_layout_payload


class UserCreateViewPreference(models.Model):
    """
    Stores the create-view field layout preference per user and content type.
    """

    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = "bloomerp_user_create_view_preference"

    user = models.ForeignKey(
        "bloomerp.User",
        on_delete=models.CASCADE,
        related_name="create_view_preference",
    )
    content_type = models.ForeignKey(
        to=ContentType,
        on_delete=models.CASCADE,
    )
    field_layout = models.JSONField(default=dict)

    @classmethod
    def get_or_create_for_user(
        cls,
        user: AbstractBloomerpUser,
        content_type_or_model: ContentType | models.Model,
    ) -> "UserCreateViewPreference":
        if isinstance(content_type_or_model, ContentType):
            content_type = content_type_or_model
        else:
            content_type = ContentType.objects.get_for_model(content_type_or_model)

        qs = cls.objects.filter(content_type=content_type, user=user)
        if qs.exists():
            preference = qs.first()
            if not preference.field_layout_obj.rows or not any(row.items for row in preference.field_layout_obj.rows):
                from bloomerp.services.create_view_services import get_default_layout

                preference.field_layout = get_default_layout(content_type=content_type, user=user).model_dump()
                preference.save(update_fields=["field_layout"])
            return preference

        return cls.create_default_for_user(user, content_type)

    @classmethod
    def create_default_for_user(
        cls,
        user: AbstractBloomerpUser,
        content_type_or_model: ContentType | models.Model,
    ) -> "UserCreateViewPreference":
        if isinstance(content_type_or_model, ContentType):
            content_type = content_type_or_model
        else:
            content_type = ContentType.objects.get_for_model(content_type_or_model)

        from bloomerp.services.create_view_services import create_default_create_view_preference

        return create_default_create_view_preference(content_type=content_type, user=user)

    def validate_field_layout(self):
        normalize_layout_payload(self.field_layout)

    @property
    def field_layout_obj(self) -> FieldLayout:
        if isinstance(self.field_layout, FieldLayout):
            return self.field_layout
        return normalize_layout_payload(self.field_layout)
