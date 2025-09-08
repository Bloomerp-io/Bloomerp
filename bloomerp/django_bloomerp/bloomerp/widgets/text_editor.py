from django import forms

class RichTextEditorWidget(forms.Textarea):
    template_name = 'widgets/tiny_mce_text_editor_widget.html'

    def get_context(self, name, value, attrs):
        attrs = attrs or {}
        attrs.setdefault('id', 'id_%s' % name)
        context = super().get_context(name, value, attrs)
        context['widget'].update({
            'editor_id': attrs['id'],
        })
        return context
