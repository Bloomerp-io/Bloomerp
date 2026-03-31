import json

from django import forms

class CodeEditorWidget(forms.Textarea):
    template_name = 'widgets/code_editor_widget.html'

    def __init__(self, attrs=None, language='python'):
        attrs = attrs or {}
        super().__init__(attrs)
        self.language = language

    def format_value(self, value):
        if self.language != 'json':
            return super().format_value(value)

        if value is None or value == '':
            return ''

        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return value

        return json.dumps(value, indent=2, ensure_ascii=False)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context['widget'].update({
            'language': self.language,
            'editor_id': f"editor_{attrs.get('id', name)}",
        })
        return context
