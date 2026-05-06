from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q

from bloomerp.models.base_bloomerp_model import BloomerpModel, FieldLayout
from bloomerp.models.users.base_view_preference import BaseViewPreference
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.services.sectioned_layout_services import normalize_layout_payload

class UserCreateViewPreference(BaseViewPreference):
    """
    Stores the create-view field layout preference per user and content type.
    """
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = "bloomerp_user_create_view_preference"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "content_type"],
                condition=Q(selected=True),
                name="unique_selected_create_view_preference",
            ),
        ]
    field_layout = models.JSONField(default=dict)

    @classmethod
    def create_default_for_user(
        cls,
        user: AbstractBloomerpUser,
        content_type_or_model: ContentType | models.Model,
    ) -> "UserCreateViewPreference":
        content_type = cls.resolve_content_type(content_type_or_model)

        from bloomerp.services.create_view_services import create_default_create_view_preference

        return create_default_create_view_preference(content_type=content_type, user=user)

    def ensure_default_state(self, *, user, content_type: ContentType) -> None:
        if not self.field_layout_obj.rows or not any(row.items for row in self.field_layout_obj.rows):
            from bloomerp.services.create_view_services import get_default_layout

            self.field_layout = get_default_layout(content_type=content_type, user=user).model_dump()
            self.save(update_fields=["field_layout"])

    def validate_field_layout(self):
        normalize_layout_payload(self.field_layout)

    @property
    def field_layout_obj(self) -> FieldLayout:
        if isinstance(self.field_layout, FieldLayout):
            return self.field_layout
        return normalize_layout_payload(self.field_layout)
