from django import forms
from bloomerp.models import ApplicationField

class BloomerpModelForm(forms.ModelForm):
    def __init__(self, data = ..., files = ..., auto_id = ..., prefix = ..., initial = ..., error_class = ..., label_suffix = ..., empty_permitted = ..., instance = ..., use_required_attribute = ..., renderer = ...):
        super().__init__(data, files, auto_id, prefix, initial, error_class, label_suffix, empty_permitted, instance, use_required_attribute, renderer)
        
        # Get the model
        self._meta.model
        
        # Get the application fields
        