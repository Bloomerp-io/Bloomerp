from django.db import models
from django import forms
from bloomerp.widgets.text_editor import RichTextEditorWidget

class TextEditorField(models.TextField):
    def formfield(self, **kwargs):
        defaults = {
            'form_class': forms.CharField,
            'widget': RichTextEditorWidget(),
        }
        defaults.update(kwargs)
        return super().formfield(**defaults)