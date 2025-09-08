from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericRelation, GenericForeignKey
from django.db.models.query import QuerySet
from bloomerp.models import mixins
import os
import uuid


# ---------------------------------
# Bloomerp Model (abstract)
# ---------------------------------
class BloomerpModel(
    mixins.TimestampedModelMixin,
    mixins.StringSearchModelMixin,
    mixins.UserStampedModelMixin,
    mixins.AbsoluteUrlModelMixin,
    mixins.AvatarModelMixin,
    models.Model,
):
    '''
    Base model for all Bloomerp models.
    '''
    class Meta:
        abstract = True
        default_permissions = ('add', 'change', 'delete', 'view', 'bulk_change', 'bulk_delete', 'bulk_add', 'export')
    
    files = GenericRelation("bloomerp.File")
    comments = GenericRelation("bloomerp.Comment")


    form_layout : dict = None

    @classmethod
    def _validate_form_layout(cls) -> tuple[bool, list[str]]:
        """Validates the whether the form layout is correct."""
        if not cls.form_layout:
            return True, []

        EXCEPTION_FIELDS = ['created_by','updated_by','datetime_created','datetime_updated']

        fields = cls._meta.concrete_fields + cls._meta.many_to_many

        field_names = [field.name for field in fields]

        fields_in_form_layout = [] # List of fields that are contained in the form layout

        for field_section, field_list in cls.form_layout.items():
            for field in field_list:
                fields_in_form_layout.append(field)

        missing_fields = set(fields_in_form_layout) - set(field_names) - set(EXCEPTION_FIELDS)

        if missing_fields:
            return False, list(missing_fields)
        else:
            return True, []
        
    @classmethod
    def _get_form_layout(cls) -> dict:
        if cls._validate_form_layout()[0] == False:
            return False
        
        enhanced_layout = {}
        for title, field_names in cls.form_layout.items():
            required = False
            for field in field_names:
                if not cls._meta.get_field(field).null:
                    required = True
            
            enhanced_layout[title] = {
                "required" : required,
                "fields" : field_names
            }

        return enhanced_layout


# ---------------------------------
# ApplicationField Model
# ---------------------------------
class ApplicationField(models.Model):
    """
    ApplicationField is a model that stores information about fields and attributes in the Django model.
    """

    allow_string_search = False

    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = "bloomerp_application_field"

    FIELD_TYPES = [
        ("Property", "Property"),
        ("AutoField", "AutoField"),
        ("ForeignKey", "ForeignKey"),
        ("FileField", "FileField"),
        ("ImageField", "ImageField"),
        ("CharField", "CharField"),
        ("TextField", "TextField"),
        ("IntegerField", "IntegerField"),
        ("FloatField", "FloatField"),
        ("DecimalField", "DecimalField"),
        ("BooleanField", "BooleanField"),
        ("DateField", "DateField"),
        ("DateTimeField", "DateTimeField"),
        ("TimeField", "TimeField"),
        ("DurationField", "DurationField"),
        ("EmailField", "EmailField"),
        ("URLField", "URLField"),
        ("UUIDField", "UUIDField"),
        ("GenericIPAddressField", "GenericIPAddressField"),
        ("SlugField", "SlugField"),
        ("PositiveIntegerField", "PositiveIntegerField"),
        ("PositiveSmallIntegerField", "PositiveSmallIntegerField"),
        ("BigIntegerField", "BigIntegerField"),
        ("SmallIntegerField", "SmallIntegerField"),
        ("BinaryField", "BinaryField"),
        ("IPAddressField", "IPAddressField"),
        ("AutoField", "AutoField"),
        ("BigAutoField", "BigAutoField"),
        ("SmallAutoField", "SmallAutoField"),
        ("NullBooleanField", "NullBooleanField"),
        ("OneToOneField", "OneToOneField"),
        ("ManyToManyField", "ManyToManyField"),
        ("ArrayField", "ArrayField"),
        ("JSONField", "JSONField"),
        ("HStoreField", "HStoreField"),
        ("BinaryField", "BinaryField"),
        ("UUIDField", "UUIDField"),
        ("ForeignKey", "ForeignKey"),
        ("OneToOneField", "OneToOneField"),
        ("ManyToManyField", "ManyToManyField"),
        ("GenericRelation", "GenericRelation"),
        ("GenericForeignKey", "GenericForeignKey"),
        ("ForeignKey", "ForeignKey"),
        ("OneToOneField", "OneToOneField"),
        ("ManyToManyField", "ManyToManyField"),
        ("GenericRelation", "GenericRelation"),
        ("GenericForeignKey", "GenericForeignKey"),
        ("ForeignKey", "ForeignKey"),
        ("OneToOneField", "OneToOneField"),
        ("ManyToManyField", "ManyToManyField"),
        ("GenericRelation", "GenericRelation"),
        ("GenericForeignKey", "GenericForeignKey"),
    ]

    field = models.CharField(max_length=100)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    field_type = models.CharField(max_length=100, choices=FIELD_TYPES)
    related_model = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True, related_name='related_models') # Related model for ForeignKey, OneToOneField, ManyToManyField
    meta = models.JSONField(null=True, blank=True)

    # Database related fields
    db_table = models.CharField(max_length=100, null=True, blank=True)
    db_field_type = models.CharField(max_length=100, null=True, blank=True)
    db_column = models.CharField(max_length=100, null=True, blank=True)

    def get_for_model(model:models.Model) -> QuerySet:
        """Returns application fields for a specific model"""
        return ApplicationField.objects.filter(
            content_type=ContentType.objects.get_for_model(model)
        )

    @property
    def title(self):
        return self.field.replace("_", " ").title()

    def __str__(self):
        return self.content_type.__str__() + " | " + str(self.field)

    @staticmethod
    def get_related_models(model: models.Model, skip_auto_created=True):
        """Returns all related models for a specific model"""
        content_type_id = ContentType.objects.get_for_model(model).pk
        qs = ApplicationField.objects.filter(
            meta__related_model=content_type_id
        ).exclude(content_type=content_type_id)
        if skip_auto_created:
            qs = qs.exclude(meta__auto_created=True)

        return qs

    @staticmethod
    def get_db_tables_and_columns(user= None) -> list[tuple[str, list[str]]]:
        """
        Returns a tuple for each database table.
        The tuple contains the table name and a tuple of the list of columns and there datatype.
        
        Args:
            user (User): The user object


        Example output:
        [
            ('auth_user', [('id', 'int'), ('username','varchar'), ...]),
            ('auth_group', [('id', 'int'), ('name','varchar'), ...]),
        ]

        """
        tables = []

        qs = ApplicationField.objects.filter(db_table__isnull=False)

        if user:
            content_types = user.get_content_types_for_user(permission_types=["view"])
            qs = qs.filter(content_type__in=content_types)


        for table in qs.values("db_table").distinct():
            table_name = table["db_table"]
            columns = ApplicationField.objects.filter(db_table=table_name).values_list(
                "db_column", "db_field_type"
            )
            tables.append((table_name, columns))
        return tables


# ---------------------------------
# File Model
# ---------------------------------
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


# ---------------------------------
# Folder Model
# ---------------------------------
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
    files = models.ManyToManyField(File, related_name='folders')
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
    

