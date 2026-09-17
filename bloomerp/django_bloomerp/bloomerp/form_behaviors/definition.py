

from dataclasses import dataclass
from typing import Callable

from django.db.models import QuerySet
from django.forms.forms import Form
from django.forms.widgets import Widget

from bloomerp.field_types.behaviors import ListenerField, TargetField
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import LayoutItem


@dataclass
class BehaviorActionDefinition:
    id:str
    label:str
    description:str
    requires_target_field:bool
    transform:Callable[[Widget], LayoutItem]
    form_factory:Callable[[TargetField, ListenerField], Form | None] = lambda _: None
    target_fields_factory:Callable[[QuerySet[ApplicationField]], QuerySet[ApplicationField]] = lambda x: x
    
    
