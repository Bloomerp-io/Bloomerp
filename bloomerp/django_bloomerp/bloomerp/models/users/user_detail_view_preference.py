from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.mixins.content_layout_model_mixin import ContentLayoutModelMixin
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.models.users.base_view_preference import BaseViewPreference

def get_default_tab_state() -> dict:
    from bloomerp.services.detail_view_services import get_default_tab_state
    return get_default_tab_state()

class UserDetailViewPreference(ContentLayoutModelMixin, BaseViewPreference):
    """
    A model to store the detail view prefernces for
    a particular model.
    """
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'bloomerp_user_detail_view_preference'
        constraints = [
            models.UniqueConstraint(
                fields=["user", "content_type"],
                condition=Q(selected=True),
                name="unique_selected_detail_view_preference",
            ),
        ]
    
    tab_state = models.JSONField(
        default=get_default_tab_state
    )
    
    @classmethod
    def create_default_for_user(cls, user:AbstractBloomerpUser, content_type_or_model:ContentType|models.Model) -> "UserDetailViewPreference":
        """Creates a default detail view preference for a certain user."""
        content_type = cls.resolve_content_type(content_type_or_model)
        from bloomerp.services.detail_view_services import create_default_detail_view_preference
        return create_default_detail_view_preference(content_type=content_type, user=user)

    def ensure_default_state(self, *, user, content_type: ContentType) -> None:
        update_fields: list[str] = []

        if not self.layout_obj.rows or not any(row.items for row in self.layout_obj.rows):
            from bloomerp.services.detail_view_services import get_default_layout

            self.layout = get_default_layout(content_type=content_type, user=user).model_dump()
            update_fields.append("layout")

        if update_fields:
            self.save(update_fields=update_fields)

    @property
    def tab_state_obj(self) -> dict:
        from bloomerp.services.detail_view_services import normalize_detail_tab_state
        if not isinstance(self.tab_state, dict):
            return get_default_tab_state()
        try:
            return normalize_detail_tab_state(self.tab_state)
        except ValueError:
            return get_default_tab_state()
    
    
    
    
    
