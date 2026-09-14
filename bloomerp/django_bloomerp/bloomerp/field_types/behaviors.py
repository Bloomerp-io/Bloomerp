

from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional

from django.forms.widgets import Widget

from bloomerp import lookups
from bloomerp.filters.definition import FilterCondition
from bloomerp.lookups.definition import LookupDefinition
from bloomerp.models.definition import LayoutItem

IS_TRUE = False

@dataclass
class BehaviorCondition:
    target_field:str
    lookup:LookupDefinition
    value: Any

@dataclass
class BehaviorActionExecutor:
    id:str
    label:str
    description:str
    required_target_field:bool
    transform:Callable[[Widget], LayoutItem]
    

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


