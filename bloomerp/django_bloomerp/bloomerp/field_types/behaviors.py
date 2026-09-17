

from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional

from django.db.models import QuerySet
from django.forms.forms import Form

from django.forms.widgets import Widget

from bloomerp import lookups
from bloomerp.filters.definition import FilterCondition
from bloomerp.lookups.definition import LookupDefinition
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import LayoutItem
from django import forms

IS_TRUE = False

@dataclass
class BehaviorCondition:
    target_field:str
    lookup:LookupDefinition
    value: Any

TargetField = ApplicationField | None

ListenerField = ApplicationField | None

@dataclass
class BehaviorActionExecutor:
    id:str
    label:str
    description:str
    requires_target_field:bool
    transform:Callable[[Widget], LayoutItem]
    form_factory:Callable[[TargetField, ListenerField], Form]
    target_fields:Callable[[QuerySet[ApplicationField]], QuerySet[ApplicationField]]
    

@dataclass
class BehaviorAction:
    target_field:str
    executor:BehaviorActionExecutor
    

@dataclass
class FormBehavior:
    name : str
    on : Literal["change", "init", "both"] = "change"
    condition:Optional[BehaviorCondition] = None
    action:BehaviorAction
    
SHOW_FIELD = BehaviorActionExecutor(
    id="show_field",
    label="Show Field",
    
)


def _fill_values_form_factory(target:ApplicationField, listener_field:ApplicationField):
    pass

class F:
    column = forms.CharField(
        
    )
    row = forms.IntegerField(
           
    )
    
    
    

def _fill_value_target_fields(afs) -> QuerySet[ApplicationField]:
    pass

FILL_VALUES = BehaviorActionExecutor(
    id="fill_values",
    label="Fill values",
    requires_target_field=True,
    form_factory=_fill_values_form_factory,
    target_fields=_fill_value_target_fields
)

LayoutItem(
    id="is_active",
    behavior=[
        FormBehavior(
            name="Show ID field",
            on="change",
            condition=BehaviorCondition(
                target_field="is_active",
                lookup=IS_TRUE               
            ),
            action=BehaviorAction(
                target_field="identification_number",
                executor=SHOW_FIELD
            )
        )
    ]
)


