from django import forms

class AceEditorWidget(forms.Textarea):
    template_name = 'widgets/ace_editor_widget.html'

    def __init__(self, attrs=None, language='python'):
        attrs = attrs or {}
        attrs.setdefault('hidden', 'true')  # Hide the textarea
        super().__init__(attrs)
        self.language = language

    class Media:
        js = ('https://cdn.jsdelivr.net/npm/ace-builds@1.4.12/src-min-noconflict/ace.js',)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context['widget'].update({
            'language': self.language,
            'editor_id': f"editor_{attrs.get('id', name)}",
        })
        return context
