from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
import os
import uuid
from bloomerp.models import mixins
from bloomerp.models.base_bloomerp_model import BloomerpModel
from django.db.models.query import QuerySet

class File(
    mixins.TimestampedModelMixin, 
    mixins.StringSearchModelMixin,
    mixins.UserStampedModelMixin,
    models.Model,
):
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = "bloomerp_file"

    search_fields = ['name']
    allow_string_search = True

    def upload_to(self, filename):
        '''Returns the upload path for the file'''
        # Can fetch this from settings in the future
        ROOT = 'bloomerp'

        if self.content_type is None:
            # Default folder for files with no content type
            folder = f'others'
        else:
            # Use the content type's app_label for organization
            folder = f'{self.content_type.app_label}'
        
        # Ensure unique file names
        unique_filename = f"{uuid.uuid4()}_{filename}"
        
        # Return the full path
        return f'{ROOT}/{folder}/{unique_filename}'
    
    # -----------------------------
    # File Fields
    # -----------------------------
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.FileField(upload_to=upload_to)
    name = models.CharField(max_length=100, null=True, blank=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.CharField(max_length=36, null=True, blank=True) # In order to support both UUID and integer primary keys
    content_object = GenericForeignKey("content_type", "object_id")
    persisted = models.BooleanField(default=False) # A field to indicate if the file is temporary or persisted

    # Created/updated utils
    meta = models.JSONField(blank=True, null=True)

    @property
    def url(self):
        return self.file.url

    @property
    def file_extension(self):
        """Returns the file extension of the file."""
        _, extension = os.path.splitext(self.file.name)
        return extension[1:]

    @property
    def size(self):
        """Returns the file size of the file."""
        try:
            return self.file.size
        except FileNotFoundError:
            return 0

    @property
    def size_str(self):
        """Returns the file size of the file in human readable format."""
        size = self.size
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.2f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / 1024 / 1024:.2f} MB"
        else:
            return f"{size / 1024 / 1024 / 1024:.2f} GB"

    def __str__(self):
        return str(self.name)


    def save(self, *args, **kwargs):
        # Check if a new file is being uploaded
        if self.pk:
            try:
                old_file = File.objects.get(pk=self.pk).file
                # If the file field is changed, delete the old file
                if old_file and old_file != self.file:
                    old_file.delete(save=False)
            except File.DoesNotExist:
                pass  # No old file exists

        # Set the name if not already set
        if not self.name:
            self.name = self.auto_name()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Delete the file when the object is deleted
        try:
            self.file.delete()
        except FileNotFoundError:
            pass
        super().delete(*args, **kwargs)

    def auto_name(self):
        """Returns the name of the file."""
        return self.file.name

    def get_accesible_files_for_user(
        query: str, 
        user, 
        folder=None, 
        content_type=None, 
        object_id=None
    ) -> QuerySet:
        """
        Returns a queryset of files that are accessible for the user.

        Args:
            query (str): The search query
            user (User): The user object
            folder (FileFolder): The folder object
            content_type (ContentType): The content type
            object_id (int): The object id

        Returns:
            QuerySet: A queryset of files
        """

        # Get the content types the user has access to
        content_types = user.get_content_types_for_user(permission_types=["view"])

        if folder:
            qs = folder.files.filter(content_type__in=content_types).order_by(
                "-datetime_created"
            )
        else:
            qs = File.objects.filter(content_type__in=content_types).order_by(
                "-datetime_created"
            )

        # Filter the queryset based on the content type
        if content_type:
            qs = qs.filter(content_type=content_type)

        # Filter the queryset based on the object id
        if object_id:
            qs = qs.filter(object_id=object_id)

        # Filter the queryset based on the query
        if query:
            qs = qs.filter(models.Q(name__icontains=query)).order_by(
                "-datetime_created"
            )

        return qs

