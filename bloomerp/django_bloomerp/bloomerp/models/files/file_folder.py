from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from bloomerp.models import mixins
from bloomerp.models.base_bloomerp_model import BloomerpModel


class FileFolder(
    mixins.TimestampedModelMixin,
    mixins.UserStampedModelMixin,
    mixins.AbsoluteUrlModelMixin,
    mixins.StringSearchModelMixin,
    models.Model,
):
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = "bloomerp_file_folder"

    name = models.CharField(max_length=255)
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True)
    content_type = models.ForeignKey(
        to=ContentType, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True)
    object_id = models.CharField(
        max_length=36, 
        null=True, 
        blank=True
        )
    content_object = GenericForeignKey(
        ct_field="content_type", 
        fk_field="object_id"
        )
    protected = models.BooleanField(
        default=False,
        help_text="Protected folders cannot be edited or deleted through the UI. This is useful for folders that are automatically created for objects, such as the module-level folders created for files.",
        )


    def __str__(self):
        return self.name

    string_search_fields = ["name"]
    allow_string_search = True

    def clean(self):
        super().clean()

        if self.object_id and not self.content_type_id:
            raise ValidationError({"content_type": "content_type is required when object_id is set."})

        if not self.parent_id:
            return

        parent = self.parent
        if parent is None:
            return

        if parent.content_type_id and self.content_type_id != parent.content_type_id:
            raise ValidationError(
                {"content_type": "Child folders must inherit the parent's content_type."}
            )

        if (parent.object_id or None) and (self.object_id or None) != (parent.object_id or None):
            raise ValidationError(
                {"object_id": "Child folders must inherit the parent's object_id."}
            )

    def save(self, *args, **kwargs):
        self.full_clean(exclude=["created_by", "updated_by"])
        return super().save(*args, **kwargs)

    @property
    def parents(self):
        """Returns a list of parent folders."""
        parents = []
        parent = self.parent
        while parent:
            parents.append(parent)
            parent = parent.parent

        # Reverse the list to get the parents in the correct order
        return list(reversed(parents))
    
    @property
    def children(self):
        """Returns a list of child folders."""
        return FileFolder.objects.filter(parent=self)
