from django.db import models
import ast
from django.core.exceptions import ValidationError


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
