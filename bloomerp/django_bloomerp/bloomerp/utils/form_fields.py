from django import forms

def render_single_field(
    *,
    model,
    instance,
    field_name,
    widget=None,
):
    attrs = {'model': model, 'fields': [field_name]}
    if widget:
        attrs['widgets'] = {field_name: widget}
    
    SingleFieldForm = type('SingleFieldForm', (forms.ModelForm,), {'Meta': type('Meta', (), attrs)})
    
    form = SingleFieldForm(instance=instance)
    return str(form[field_name])
