from bloomerp.models.application_field import ApplicationField
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.models.files import File
from bloomerp.models.users.user_detail_view_preference import UserDetailViewPreference
from django import forms
from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from uuid import UUID
from bloomerp.utils.models import (
    get_bloomerp_file_fields_for_model,
    get_foreign_key_fields_for_model
    )
from django.contrib.postgres.fields import JSONField
from django.db.models import JSONField as DefaultJSONField
from bloomerp.widgets.code_editor_widget import CodeEditorWidget
from django.forms.widgets import DateInput, DateTimeInput
from bloomerp.forms.layouts import BloomerpModelformHelper
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget
from bloomerp.models import UserDetailViewPreference

# ---------------------------------
# Bloomerp Bulk Upload Form
# ---------------------------------
class BulkUploadForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super(BulkUploadForm, self).__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field, forms.BooleanField):
                self.fields[name].widget = forms.Select(choices=[(True, 'True'), (False, 'False')])

        # Add delete all objects
        self.fields['delete_all'] = forms.BooleanField(required=False, label='Delete all selected objects',initial=False)

        # Remove last_updated_by field
        if 'last_updated_by' in self.fields:
            del self.fields['last_updated_by']


# ---------------------------------
# Bloomerp Model Form
# ---------------------------------
class BloomerpModelForm(forms.ModelForm):
    model:Model = None
    user:AbstractBloomerpUser = None
    instance:Model = None
    is_new_instance:bool = True

    def __init__(
            self, 
            model:Model, 
            user:AbstractBloomerpUser=None,
            apply_helper=True,
            hide_default_fields=True,
            *args, **kwargs):
        '''
        Args:
            model: The model for which the model form is made
            user: The user who is filling in the model form
            apply_helper: whether to apply the layout
            hide_default_fields: whether to hide the default fields (created_by, updated_by)
        
        '''
        # Set the model instance to the form instance
        self.model = model
        self._meta.model = model
        self.user = user

        super(BloomerpModelForm, self).__init__(*args, **kwargs)
        
        # Set the instance to the form instance
        instance:Model = kwargs.get('instance')
        if instance:
            self.instance = instance
            self.is_new_instance = False

        # Get all of the foreign key fields for the model
        self.foreign_key_fields = get_foreign_key_fields_for_model(self.model)

        
        # ---------------------------------
        # FOREIGN KEY FIELDS
        # ---------------------------------
        # Update the widgets for the foreign key fields
        for field in self.foreign_key_fields:
            # Get the related model
            if field.field in self.fields:
                related_model = field.meta['related_model']
                model = ContentType.objects.get(pk=related_model).model_class()
                widget_attrs = {
                    'class' : 'input',
                    'model' : model,
                }
                widget_attrs.update(field.meta or {})
                self.fields[field.field].widget = ForeignFieldWidget(attrs=widget_attrs)
        
        # ---------------------------------
        # MANY TO MANY FIELDS
        # ---------------------------------
        # Update the widgets for many to many fields
        for field in self._meta.model._meta.many_to_many:
            if field.name in self.fields:
                related_model = field.remote_field.model
                self.fields[field.name].widget = ForeignFieldWidget(
                    attrs={"model": related_model, "is_m2m": True}
                    )
    
        # ---------------------------------
        # FILE FIELDS
        # ---------------------------------
        # Update the widgets for the file fields
        self.file_fields = get_bloomerp_file_fields_for_model(self.model, output='list')

        # ---------------------------------
        # DATE AND DATETIME FIELDS
        # ---------------------------------
        for field_name, field in self.fields.items():
            if isinstance(field, forms.DateField):
                self.fields[field_name].widget = DateInput(attrs={'type': 'date'})
            elif isinstance(field, forms.DateTimeField):
                self.fields[field_name].widget = DateTimeInput(attrs={'type': 'datetime-local'})

        # ---------------------------------
        # JSON FIELDS
        # ---------------------------------
        # Update the widgets for the json fields
        for field_name, field in self.fields.items():
            # Check if the field is a JSONField
            model_field = self._meta.model._meta.get_field(field_name)
            
            if isinstance(model_field, (JSONField, DefaultJSONField)):
                # Apply the CodeEditorWidget for JSON fields
                self.fields[field_name].widget = CodeEditorWidget(language='json')

        # ---------------------------------
        # Hide created_by and updated_by fields
        # ---------------------------------
        if hide_default_fields:
            if 'created_by' in self.fields:
                del self.fields['created_by']
            if 'updated_by' in self.fields:
                del self.fields['updated_by']

        if self.model and apply_helper:
            helper = BloomerpModelformHelper([])

            if helper.is_defined() and self.model:
                self.helper = helper
        
    def save(self, commit=True):
        instance = super(BloomerpModelForm, self).save(commit=False)

        # Check if the instance is new by checking if it has no primary key
        is_new_instance = instance.pk is None

        # Mark all temporary files as finalized after successful save
        def save_file_fields():
            if not instance.pk:
                raise ValueError("Instance must be saved before saving file fields")

            for field in self.file_fields:
                file:File = self.cleaned_data.get(field, None)
                if file:
                    # There is a new file so it has to be updated
                    file.persisted = True
                    file.content_type = ContentType.objects.get_for_model(self.model)
                    file.object_id = instance.pk
                    file.updated_by = self.user
                    file.created_by = self.user
                    file.save()
                else:
                    # There is no file, so we should delete the old file if it exists
                    old_file : File = getattr(instance, field, None)
                    if old_file:
                        old_file.delete()

        if commit:
            instance.save()
            save_file_fields()
        else:
            instance.save_file_fields = save_file_fields
            instance.is_new_instance = is_new_instance
        
        return instance

    def add_prefix(self, field_name):
        """
        Return the field name with a prefix appended.
        Overrides the default if the prefix contains "__".
        """
        if self.prefix and "__" in self.prefix:
            # Use "__" as the separator if the prefix contains "__"
            return f"{self.prefix}{field_name}"
        else:
            # Default behavior: use superclass method with hyphen separator
            return super().add_prefix(field_name)
    
# ---------------------------------
# Links select form
# ---------------------------------





