from django.forms.widgets import Widget, ClearableFileInput
from bloomerp.models.core import File
import uuid


class BloomerpFileFieldWidget(Widget):
    template_name = 'widgets/bloomerp_file_field_widget.html'
    file_input = None

    def __init__(self, attrs=None):
        self.file_input = ClearableFileInput(attrs=attrs)
        super().__init__(attrs)

    def get_context(self, name, value, attrs):
        # Set default attributes if they are not provided
        if attrs is None:
            attrs = {}

        # Check if it was marked as invalid, in that case delete the file
        if attrs.get('aria-invalid', 'false') == 'true':
            invalid = True
            File.objects.filter(pk=value).delete()
            value = None
        else:
            invalid = False
        
        # Add your custom attributes, like 'class' for Bootstrap form control
        attrs.setdefault('class', 'form-control')

        # Set value for the file field if it exists
        # This will be used to display the file name in the template
        if value:
            file_obj = File.objects.get(pk=value)
            value = file_obj.file

        # Use ClearableFileInput's get_context but with modified attrs
        context = self.file_input.get_context(name, value, attrs)

        if invalid:
            context['invalid'] = True

        if value:
            context['current_file'] = file_obj

        return context

    def value_from_datadict(self, data, files, name):
        file = self.file_input.value_from_datadict(data, files, name)

        # Check if there already is a current file instance
        current_file = data.get(name + '_current', None)
    
        # If the file is cleared, the file instance will be False, so we should return None
        if file is False:
            return None

        # If no file is provided, the value_from_datadict method will return None
        # However, we need to check if there is a current file instance
        if file is None and not current_file:
            # Case when there is no current file and no new file
            return None
        elif file is None and current_file:
            # Case when there is a current file but no new file
            return current_file
        elif file is not None and not current_file:
            # Create or update the file instance
            file_obj = File(
                file=file,
                name=file.name,
                persisted=False
            )
            # Temporarily save the file in memory
            file_obj.save()
            return file_obj.pk
        else:
            # Case when there is a current file and a new file
            # Update the current file instance
            file_obj = File.objects.get(pk=current_file)
            file_obj.file = file
            file_obj.name = file.name
            file_obj.save()
            return file_obj.pk
        

    # Pass-through methods to ClearableFileInput (you can omit these if already implemented)
    def format_value(self, value):
        return self.file_input.format_value(value)

    def clear_checkbox_name(self, name):
        return self.file_input.clear_checkbox_name(name)

    def clear_checkbox_id(self, name):
        return self.file_input.clear_checkbox_id(name)

    def is_initial(self, value):
        return self.file_input.is_initial(value)

    def value_omitted_from_data(self, data, files, name):
        return self.file_input.value_omitted_from_data(data, files, name)

    def use_required_attribute(self, initial):
        return self.file_input.use_required_attribute(initial)
