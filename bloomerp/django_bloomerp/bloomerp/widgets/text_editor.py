from django import forms

class BloomerpTextEditorWidget(forms.Textarea):
    template_name = 'cotton/ui/inputs/text_editor.html'

    def get_context(self, name, value, attrs):
        attrs = attrs or {}
        attrs.setdefault('id', 'id_%s' % name)
        context = super().get_context(name, value, attrs)
        widget_context = context.get('widget', {})
        new_context = {**widget_context.get('attrs', {})}
        new_context.update({
            'name': widget_context.get('name'),
            'value': widget_context.get('value'),
            'disabled': widget_context.get('attrs', {}).get('disabled', False),
        })
        return new_context
