from email.policy import default

from django import forms

class BloomerpTextEditorWidget(forms.Textarea):
    template_name = 'cotton/ui/inputs/text_editor.html'

    def get_context(self, name, value, attrs):
        attrs = attrs or {}
        attrs.setdefault('id', 'id_%s' % name)
        context = super().get_context(name, value, attrs)
        widget_context = context.get('widget', {})
        widget_classes = widget_context.get('attrs', {}).get('class', '').split()
        new_context = {**widget_context.get('attrs', {})}
        new_context.update({
            'name': widget_context.get('name'),
            'value': widget_context.get('value'),
            'disabled': widget_context.get('attrs', {}).get('disabled', False),
            'include_toolbar' : True,
            'compact': 'one-to-many-field-widget__input' in widget_classes,
            'has_border' : attrs.get("has_border", False)
        })
        return new_context
