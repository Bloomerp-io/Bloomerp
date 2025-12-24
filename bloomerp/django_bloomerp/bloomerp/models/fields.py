from django.db import models
import ast
from django.core.exceptions import ValidationError
import os


# ---------------------------------
# Bloomerp File Field
# ---------------------------------
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
        from bloomerp.widgets.bloomerp_file_field_widget import BloomerpFileFieldWidget

        defaults = {
            'widget': BloomerpFileFieldWidget(),
        }

        defaults.update(kwargs)
        return super().formfield(**defaults)
        
    def validate_file_extension(self, file_instance: "File"):
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

# ---------------------------------
# Bloomerp Code Field
# ---------------------------------
class CodeField(models.TextField):
    '''
    A custom model field to store code snippets with syntax highlighting.
    '''
    def __init__(self, *args, language='python', **kwargs):
        self.language = language
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        """
        This method tells Django how to serialize the field for migrations.
        """
        name, path, args, kwargs = super().deconstruct()
        kwargs['language'] = self.language
        return name, path, args, kwargs

    def formfield(self, **kwargs):
        """
        Specifies the default form field and widget to use with this model field.
        """
        from django import forms
        from bloomerp.widgets.code_editor_widget import AceEditorWidget  # Import your custom widget

        defaults = {
            'form_class': forms.CharField,
            'widget': AceEditorWidget(language=self.language),
        }
        defaults.update(kwargs)
        return super().formfield(**defaults)

    # Optional: Add custom validation logic if needed
    def validate(self, value, model_instance):
        super().validate(value, model_instance)
        # Example: Add syntax validation for Python code
        if self.language == 'python':
            import ast
            try:
                ast.parse(value)
            except SyntaxError as e:
                raise ValidationError(f"Invalid Python code: {e}")


# ---------------------------------
# Bloomerp Text Editor Field
# ---------------------------------
class TextEditorField(models.TextField):
    '''Use this field to store rich text content with a text editor.'''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    def formfield(self, **kwargs):
        from django import forms
        from bloomerp.widgets.text_editor import RichTextEditorWidget

        defaults = {
            'form_class': forms.CharField,
            'widget': RichTextEditorWidget(),
        }
        defaults.update(kwargs)
        return super().formfield(**defaults)


# ---------------------------------
# Bloomerp Status Field
# ---------------------------------
class StatusField(models.CharField):
    '''
    A status field inherits from CharField and provides a list of choices and colors.
    It is used to represent the status of a particular object and has color highlighting in the UI.

    Required Arguments:
        colored_choices: A list of tuples where each tuple contains a status, a human-readable name, and a color code (hex code).

    Example Usage:
    ```python
    class Task(models.Model):
        status = StatusField(
            max_length=20,
            colored_choices=[
                ('new', 'New', StatusField.BLUE),
                ('in_progress', 'In Progress', StatusField.ORANGE),
                ('completed', 'Completed', StatusField.GREEN),
            ]
        )
    ```
    '''

    RED = '#ff0000'
    GREEN = '#00ff00'
    BLUE = '#0000ff'
    YELLOW = '#ffff00'
    ORANGE = '#ffa500'
    PURPLE = '#800080'
    CYAN = '#00ffff'
    PINK = '#ff69b4'
    GREY = '#808080'
    BLACK = '#000000'
    WHITE = '#ffffff'

    def __init__(
            self,
            colored_choices: list[tuple[str, str, str]], 
            *args, 
            **kwargs):
        # Turn the colored_choices list into a list of choices
        choices = [(choice[0], choice[1]) for choice in colored_choices]

        # Set the color_choices attribute
        self.colored_choices = colored_choices

        # Call the parent class constructor
        kwargs['choices'] = choices
        super().__init__(*args, **kwargs)

    def get_internal_type(self):
        return "StatusField"

    def db_type(self, connection):
        """
        Returns the database type for this field.
        """
        return 'varchar({})'.format(self.max_length)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs['colored_choices'] = self.colored_choices
        return name, path, args, kwargs
