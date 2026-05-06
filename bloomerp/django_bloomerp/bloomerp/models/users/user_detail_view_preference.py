from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.models.users.base_view_preference import BaseViewPreference
from bloomerp.models.base_bloomerp_model import FieldLayout
from bloomerp.services.sectioned_layout_services import normalize_layout_payload

def get_default_tab_state() -> dict:
    from bloomerp.services.detail_view_services import get_default_tab_state
    return get_default_tab_state()

class UserDetailViewPreference(BaseViewPreference):
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
    
    field_layout = models.JSONField(
        default=dict
    )

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

        if not self.field_layout_obj.rows or not any(row.items for row in self.field_layout_obj.rows):
            from bloomerp.services.detail_view_services import get_default_layout

            self.field_layout = get_default_layout(content_type=content_type, user=user).model_dump()
            update_fields.append("field_layout")

        if update_fields:
            self.save(update_fields=update_fields)

    def validate_field_layout(self):
        normalize_layout_payload(self.field_layout)
        
    @property
    def field_layout_obj(self) -> FieldLayout:
        if isinstance(self.field_layout, FieldLayout):
            return self.field_layout
        return normalize_layout_payload(self.field_layout)

    @property
    def tab_state_obj(self) -> dict:
        from bloomerp.services.detail_view_services import normalize_detail_tab_state
        if not isinstance(self.tab_state, dict):
            return get_default_tab_state()
        try:
            return normalize_detail_tab_state(self.tab_state)
        except ValueError:
            return get_default_tab_state()
    
    
    
    
    
