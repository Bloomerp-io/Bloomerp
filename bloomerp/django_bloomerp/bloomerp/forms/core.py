from bloomerp.models import ApplicationField, AbstractBloomerpUser, File, UserDetailViewTab, Link, UserListViewPreference, UserDetailViewPreference
from django import forms
from django.contrib.contenttypes.models import ContentType
from django.forms.models import modelform_factory
from django.db.models import Model
from uuid import UUID
from bloomerp.utils.models import (
    get_bloomerp_file_fields_for_model,
    get_foreign_key_fields_for_model
    )
from django.contrib.postgres.fields import JSONField
from django.db.models import JSONField as DefaultJSONField
from bloomerp.widgets.foreign_key_widget import ForeignKeyWidget
from bloomerp.widgets.code_editor_widget import AceEditorWidget
from bloomerp.widgets.multiple_model_select_widget import MultipleModelSelect
from django.forms.widgets import DateInput, DateTimeInput
from bloomerp.forms.layouts import BloomerpModelformHelper

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
                self.fields[field.field].widget = ForeignKeyWidget(model=model)
        
        # ---------------------------------
        # MANY TO MANY FIELDS
        # ---------------------------------
        # Update the widgets for many to many fields
        for field in self._meta.model._meta.many_to_many:
            if field.name in self.fields:
                related_model = field.remote_field.model
                self.fields[field.name].widget = MultipleModelSelect(model=related_model)
    
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
                # Apply the AceEditorWidget for JSON fields
                self.fields[field_name].widget = AceEditorWidget(language='json')

        # ---------------------------------
        # Hide created_by and updated_by fields
        # ---------------------------------
        if hide_default_fields:
            if 'created_by' in self.fields:
                del self.fields['created_by']
            if 'updated_by' in self.fields:
                del self.fields['updated_by']

        
        if self.model and apply_helper:
            helper = BloomerpModelformHelper(self.model)

            if helper.is_defined() and self.model:
                self.helper = helper

                
    def save(self, commit=True):
        '''
        Saves the form instance to the database

        '''

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
# Bloomerp Field Select Form
# ---------------------------------    
class BloomerpDownloadBulkUploadTemplateForm(forms.Form):
    file_type = forms.ChoiceField(choices=[('csv', 'CSV'), ('xlsx', 'Excel')])

    def __init__(self, model: Model = None, skip_fields=True, make_required=True, *args, **kwargs):
        super(BloomerpDownloadBulkUploadTemplateForm, self).__init__(*args, **kwargs)
        # Check if the content_type_id is provided in the request.POST
        content_type_id = kwargs.get('data', {}).get('content_type_id', None)
        if content_type_id:
            try:
                self.model = ContentType.objects.get(pk=content_type_id).model_class()
            except ContentType.DoesNotExist:
                self.model = None
        elif model:
            self.model = model
        else:
            raise ValueError("Model or content_type_id must be provided")

        if not self.model:
            raise ValueError("Model could not be determined.")

        # Init skip fields
        if skip_fields:
            skip_fields = [
                'created_by',
                'updated_by',
                'datetime_created',
                'datetime_updated',
            ]
        else:
            skip_fields = []

        # Model fields
        self.model_fields = []


        # Create model form and copy the fields
        ModelForm = modelform_factory(self.model, exclude=skip_fields)
        form_instance = ModelForm()

        # Add the fields to the form
        for field_name, field in form_instance.fields.items():
            if make_required:
                required = field.required
            else:
                required = False

            self.fields[field_name] = forms.BooleanField(
                label=field.label,
                required=field.required,
                initial=field.required,
                disabled=False,
                help_text=field.help_text
            )

            # Add the field to the model fields
            self.model_fields.append(field_name)

        # Add content type id as hidden field
        self.fields['content_type_id'] = forms.IntegerField(widget=forms.HiddenInput(), initial=ContentType.objects.get_for_model(self.model).pk)

    def get_selected_fields(self):
        # Run the clean method to get the selected fields
        if self.is_valid():
            # Only include fields that are checked and in the model fields
            return [field for field in self.model_fields if self.cleaned_data.get(field, False)]
        return []
    

# ---------------------------------
# Links select form
# ---------------------------------
class DetailLinksSelectForm(forms.Form):
    def __init__(self, content_type:ContentType, user:AbstractBloomerpUser, *args, **kwargs):
        super(DetailLinksSelectForm, self).__init__(*args, **kwargs)
        
        # Get all of the links that are available for the content type
        qs = Link.objects.filter(content_type=content_type, level='DETAIL').order_by('name')
        
        for link in qs:
            if link.number_of_args() > 1:
                # Exclude links that require more than one argument
                qs = qs.exclude(pk=link.pk)
        
        # Get the links that the user has access to
        detail_view_links = UserDetailViewTab.get_detail_view_tabs(content_type=content_type, user=user).values_list('link_id', flat=True)

        self.fields['links'] = forms.ModelMultipleChoiceField(
            queryset=qs,
            widget=forms.CheckboxSelectMultiple
        )

        self.fields['links'].initial = detail_view_links

        # Add content type id as hidden field
        self.fields['content_type_id'] = forms.IntegerField(widget=forms.HiddenInput(), initial=content_type.pk)

        self.user = user


    def save(self) -> None:
        content_type_id = self.cleaned_data.get('content_type_id')
        content_type = ContentType.objects.get(pk=content_type_id)
        links = self.cleaned_data.get('links')

        # Get existing UserDetailViewTab objects for the user and content type
        existing_tabs = UserDetailViewTab.objects.filter(user=self.user, link__content_type=content_type)

        # Determine which links need to be added and which need to be removed
        existing_link_ids = set(existing_tabs.values_list('link_id', flat=True))
        selected_link_ids = set(links.values_list('id', flat=True))

        # Links to add
        links_to_add = selected_link_ids - existing_link_ids
        # Links to remove
        links_to_remove = existing_link_ids - selected_link_ids

        # Add new UserDetailViewTab objects
        for link_id in links_to_add:
            UserDetailViewTab.objects.create(user=self.user, link_id=link_id)

        # Remove UserDetailViewTab objects
        UserDetailViewTab.objects.filter(user=self.user, link_id__in=links_to_remove).delete()


# ---------------------------------
# Links select form
# ---------------------------------
class ApplicationFieldModelChoiceField(forms.ModelMultipleChoiceField):
    '''Special model choice field for ApplicationField model'''

    def label_from_instance(self, obj:ApplicationField) -> str:
        # Customize the label here, e.g., add additional details
        string = obj.field
        return string.replace('_', ' ').capitalize()

class ListViewFieldsSelectForm(forms.Form):
    def __init__(self, content_type:ContentType, user:AbstractBloomerpUser, *args, **kwargs):
        super(ListViewFieldsSelectForm, self).__init__(*args, **kwargs)
                

        # Get all of the Application fields that are available for the content type
        qs = ApplicationField.objects.filter(content_type=content_type).order_by('field')
        
        
        # Get the links that the user has access to
        application_fields = UserListViewPreference.objects.filter(user=user, application_field__in=qs).values_list('application_field_id', flat=True)
        
        self.fields['fields'] = ApplicationFieldModelChoiceField(
            queryset=qs,
            widget=forms.CheckboxSelectMultiple
        )

        self.fields['fields'].initial = application_fields
        self.fields['fields'].label = '' 

        # Add content type id as hidden field
        self.fields['content_type_id'] = forms.IntegerField(widget=forms.HiddenInput(), initial=content_type.pk)

        self.user = user


    def save(self) -> None:
        content_type_id = self.cleaned_data.get('content_type_id')
        content_type = ContentType.objects.get(pk=content_type_id)
        fields = self.cleaned_data.get('fields')

        # Get existing UserListViewPreference objects for the user and content type
        existing_preferences = UserListViewPreference.objects.filter(user=self.user, application_field__content_type=content_type)

        # Determine which fields need to be added and which need to be removed
        existing_field_ids = set(existing_preferences.values_list('application_field_id', flat=True))
        selected_field_ids = set(fields.values_list('id', flat=True))

        # Fields to add
        fields_to_add = selected_field_ids - existing_field_ids
        # Fields to remove
        fields_to_remove = existing_field_ids - selected_field_ids

        # Add new UserListViewPreference objects
        for field_id in fields_to_add:
            UserListViewPreference.objects.create(user=self.user, application_field_id=field_id)

        # Remove UserListViewPreference objects
        UserListViewPreference.objects.filter(user=self.user, application_field_id__in=fields_to_remove).delete()

