from django.core.exceptions import ValidationError
from django.db import models


import ast


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