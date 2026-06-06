from typing import Optional
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bloomerp.models import ApplicationField

from django import forms


from dataclasses import dataclass, field as dataclass_field
from typing import Any, Callable


@dataclass
class FieldDisplayOption:
    id: str
    label: str
    form_field_cls: type[forms.Field]
    required: bool = False
    default: Any = None
    help_text: str = ""
    form_field_kwargs: dict[str, Any] = dataclass_field(default_factory=dict)
    get_form_field_kwargs: Optional[Callable[["ApplicationField"], dict[str, Any]]] = None

    def build_form_field(self, application_field: "ApplicationField") -> forms.Field:
        kwargs = {
            "label": self.label,
            "required": self.required,
            "help_text": self.help_text,
            **self.form_field_kwargs,
        }
        if self.get_form_field_kwargs:
            kwargs.update(self.get_form_field_kwargs(application_field))
        return self.form_field_cls(**kwargs)