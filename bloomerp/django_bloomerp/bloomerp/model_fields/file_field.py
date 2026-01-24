from django.core.exceptions import ValidationError
from django.db import models
import os
from bloomerp.widgets.file_field_widget import BloomerpFileFieldWidget

class BloomerpFileField(models.ForeignKey):
    def __init__(self, *args, allowed_extensions=None, **kwargs):
        """
        Initialize BloomerpFileField with a ForeignKey to the File model and optional file type validation.
        `allowed_extensions` specifies allowed file types; if '__all__' or None, all are allowed.
        """
        self.allowed_extensions = allowed_extensions if allowed_extensions is not None else '__all__'
        kwargs['to'] = 'bloomerp.File'
        kwargs['on_delete'] = models.SET_NULL
        kwargs['null'] = True
        kwargs['blank'] = True # Field should always be optional as we dont want any cascading 

        super().__init__(*args, **kwargs)

    def formfield(self, **kwargs):
        """
        Specifies the default form field and widget to use with this model field.
        """
        defaults = {
            'widget': BloomerpFileFieldWidget(),
        }

        defaults.update(kwargs)
        return super().formfield(**defaults)

    def validate_file_extension(self, file_instance):
        """
        Validate the file extension of the file associated with the foreign key.
        """
        # If allowed_extensions is '__all__', no restriction on file types
        if self.allowed_extensions == '__all__':
            return

        # Get the file extension of the associated file
        ext = os.path.splitext(file_instance.file.name)[1].lower()

        # Check if the extension is in the allowed list
        if ext not in self.allowed_extensions:
            allowed_ext_str = ', '.join(self.allowed_extensions)
            raise ValidationError(f'Unsupported file extension. Allowed extensions are: {allowed_ext_str}')

    def clean(self, value, model_instance):
        """
        Perform the validation on the foreign key reference and ensure the file type is allowed.
        """
        from bloomerp.models.files.file import File

        # Call the parent clean method to validate the ForeignKey relationship
        value = super().clean(value, model_instance)

        file_instance = File.objects.get(pk=value)

        # Validate the file extension of the linked file object
        if value:  # Ensure that a valid file instance is passed
            self.validate_file_extension(file_instance)

        return value