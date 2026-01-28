from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.conf import settings
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.models.base_bloomerp_model import FieldLayout

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
    
    @classmethod
    def get_or_create_for_user(user:AbstractBloomerpUser, content_type_or_model:ContentType|models.Model) -> "UserDetailViewPreference":
        """Returns the detail view preference for a certain user.

        Args:
            user (AbstractBloomerpUser): the user
            content_type_or_model (models.Model | ContentType): the content type or model

        Returns:
            UserDetailViewPreference: the detail view object
        """
        pass
    
    @classmethod
    def create_default_for_user(user:AbstractBloomerpUser, content_type_or_model:ContentType|models.Model) -> "UserDetailViewPreference":
        """Creates a default detail view preference for a certain user.

        Args:
            user (AbstractBloomerpUser): the user
            content_type_or_model (models.Model | ContentType): the content type or model

        Returns:
            UserDetailViewPreference: the detail view object
        """
        pass
    
    
    def validate_field_layout(self):
        FieldLayout.model_dump(self.field_layout)
        
    @property
    def field_layout_obj(self) -> FieldLayout:
        # `field_layout` is stored as JSON (dict) in the DB; convert it to a FieldLayout object.
        if isinstance(self.field_layout, FieldLayout):
            return self.field_layout
        return FieldLayout.model_validate(self.field_layout)
    
    
    
    
    
