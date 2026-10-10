from django.utils.translation import gettext_lazy as _

from django.db import models
from bloomerp.model_fields.labels_field import BloomerpLabelsField
from django.contrib.contenttypes.fields import GenericRelation
from bloomerp.models.mixins.absolute_url_model_mixin import AbsoluteUrlModelMixin
from bloomerp.models.mixins.avatar_model_mixin import AvatarModelMixin
from bloomerp.models.mixins.timestamp_model_mixin import TimestampModelMixin
from bloomerp.models.mixins.user_stamp_model_mixin import UserStampModelMixin
from bloomerp.models.mixins.uuid_model_mixin import UuidModelMixin
from bloomerp.permissions.definition import BloomerpPermission

class BloomerpModel(
    UuidModelMixin,
    TimestampModelMixin,
    UserStampModelMixin,
    AbsoluteUrlModelMixin,
    AvatarModelMixin,
    models.Model,
):
    class Meta:
        abstract = True
        default_permissions = BloomerpPermission.to_tuple()
    
    files = GenericRelation("bloomerp.FileReference")
    comments = GenericRelation("bloomerp.Comment")
    object_labels = BloomerpLabelsField(verbose_name=_("Object labels"))




    
