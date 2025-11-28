from django.db import models
from django.contrib.contenttypes.fields import GenericRelation
from bloomerp.models import mixins

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
