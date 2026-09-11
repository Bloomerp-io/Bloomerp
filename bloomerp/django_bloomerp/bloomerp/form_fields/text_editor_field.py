from django import forms

from bloomerp.widgets.text_editor import BloomerpTextEditorWidget


class TextEditorFormField(forms.CharField):
    """A character field rendered with BloomERP's rich-text editor widget."""

    widget = BloomerpTextEditorWidget
