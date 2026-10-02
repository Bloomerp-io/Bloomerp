from bloomerp.models import TimestampModelMixin
from bloomerp.models.mixins.user_stamp_model_mixin import UserStampModelMixin
from bloomerp.models import BloomerpModel
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils.html import strip_tags
from django.utils.text import Truncator

class Comment(
    TimestampModelMixin,
    UserStampModelMixin,
    models.Model,
):
    class Meta(BloomerpModel.Meta):
        verbose_name = _("Comment")
        verbose_name_plural = _("Comments")
        managed = True
        db_table = 'bloomerp_comment'
    
    avatar = None
    
    content_type = models.ForeignKey(
        ContentType, 
        on_delete=models.CASCADE,
        verbose_name=_("Content Type")
    )
    object_id = models.CharField(
        max_length=36,
        verbose_name=_("Object ID"),
        help_text=_("In order to support both UUID and integer primary keys")
    )
    content_object = GenericForeignKey(
        "content_type", "object_id"
    )
    content = models.TextField(
        verbose_name=_("Content"),
    )

    def __str__(self) -> str:
        """Return a short plain-text label for rich-text comment content."""
        content = Truncator(strip_tags(self.content)).chars(80)
        return content or f"Comment {self.pk}"

    def get_absolute_url(self) -> str:
        """Link to a redirect that resolves the related object when opened."""
        return reverse("comment_detail_redirect", kwargs={"comment_id": self.pk})
