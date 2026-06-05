from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q

from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.mixins.content_layout_model_mixin import ContentLayoutModelMixin
from bloomerp.models.users.base_view_preference import BaseViewPreference
from bloomerp.models.users.user import AbstractBloomerpUser

class UserCreateViewPreference(ContentLayoutModelMixin, BaseViewPreference):
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
        if not self.layout_obj.rows or not any(row.items for row in self.layout_obj.rows):
            from bloomerp.services.create_view_services import get_default_layout

            self.layout = get_default_layout(content_type=content_type, user=user).model_dump()
            self.save(update_fields=["layout"])
