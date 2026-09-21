from typing import Any, Iterable

from django import forms


Value = Any
Label = str

class MappingField(forms.JSONField):
    def __init__(self, left:list[tuple[Value, Label]], right:list[tuple[Value, Label]], *args, **kwargs):
        pass