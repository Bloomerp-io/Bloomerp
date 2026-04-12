from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.conf import settings
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.models.base_bloomerp_model import FieldLayout
from bloomerp.services.sectioned_layout_services import normalize_layout_payload


def get_default_tab_state() -> dict:
    from bloomerp.services.detail_view_services import get_default_tab_state_v2
    return get_default_tab_state_v2()

class UserDetailViewPreference(models.Model):
    """
    A model to store the detail view prefernces for
    a particular model.
    """
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'bloomerp_user_detail_view_preference'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE,
        related_name = 'detail_view_preference'
        )
    content_type = models.ForeignKey(
        to=ContentType, 
        on_delete=models.CASCADE
        )
    
    field_layout = models.JSONField(
        default=dict
    )

    tab_state = models.JSONField(
        default=get_default_tab_state
    )
    
    @classmethod
    def get_or_create_for_user(cls, user:AbstractBloomerpUser, content_type_or_model:ContentType|models.Model) -> "UserDetailViewPreference":
        """Returns the detail view preference for a certain user.

        Args:
            user (AbstractBloomerpUser): the user
            content_type_or_model (models.Model | ContentType): the content type or model

        Returns:
            UserDetailViewPreference: the detail view object
        """
        if isinstance(content_type_or_model, ContentType):
            content_type = content_type_or_model
        else:
            content_type = ContentType.objects.get_for_model(content_type_or_model)

        qs = UserDetailViewPreference.objects.filter(
            content_type=content_type,
            user=user,
        )
        if qs.exists():
            preference = qs.first()
            if not preference.field_layout_obj.rows or not any(row.items for row in preference.field_layout_obj.rows):
                from bloomerp.services.detail_view_services import get_default_layout
                preference.field_layout = get_default_layout(content_type=content_type, user=user).model_dump()
                preference.save(update_fields=["field_layout"])
            return preference

        return UserDetailViewPreference.create_default_for_user(user, content_type)
    
    @classmethod
    def create_default_for_user(cls, user:AbstractBloomerpUser, content_type_or_model:ContentType|models.Model) -> "UserDetailViewPreference":
        """Creates a default detail view preference for a certain user.

        Args:
            user (AbstractBloomerpUser): the user
            content_type_or_model (models.Model | ContentType): the content type or model

        Returns:
            UserDetailViewPreference: the detail view object
        """
        if isinstance(content_type_or_model, ContentType):
            content_type = content_type_or_model
        else:
            content_type = ContentType.objects.get_for_model(content_type_or_model)

        from bloomerp.services.detail_view_services import create_default_detail_view_preference
        return create_default_detail_view_preference(content_type=content_type, user=user)
    
    
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
        return normalize_detail_tab_state(self.tab_state)
    
    
    
    
    
