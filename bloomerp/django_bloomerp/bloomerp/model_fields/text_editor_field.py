from django.db import models

from bloomerp.form_fields.text_editor_field import TextEditorFormField
from bloomerp.widgets.text_editor import BloomerpTextEditorWidget


class TextEditorField(models.TextField):
    def formfield(self, **kwargs):
        defaults = {
            "form_class": TextEditorFormField,
            "widget": BloomerpTextEditorWidget(),
        }
        defaults.update(kwargs)
        return super().formfield(**defaults)
