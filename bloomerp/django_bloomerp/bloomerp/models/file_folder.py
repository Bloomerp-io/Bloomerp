from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.db.models.query import QuerySet
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
    files = models.ManyToManyField('bloomerp.File', related_name='folders')
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True)
    content_types = models.ManyToManyField(ContentType, help_text="Restrict folders to certain models.", verbose_name="Models")

    def __str__(self):
        return self.name
    
    string_search_fields = ['name']
    allow_string_search = True


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
    

