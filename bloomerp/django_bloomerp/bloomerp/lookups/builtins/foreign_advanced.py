from __future__ import annotations

from typing import Type

from django.db.models import Model

from bloomerp.lookups.definition import LookupDefinition


def _nested_fields(model:Type[Model], field_path:str) -> list[FilterField]:
    from bloomerp.filters.definition import FilterField
    from bloomerp.filters.utils import application_fields_to_filter_field_groups
    from bloomerp.middleware import current_request
    from bloomerp.models.application_field import ApplicationField
    from bloomerp.permissions.definition import BloomerpPermission
    from bloomerp.permissions.manager import UserPolicyManager
    parts = field_path.split["__"]
    
    # traverse through the
    terminal_model = None
    
    request = current_request()
    if request:
        return application_fields_to_filter_field_groups(
            UserPolicyManager(request.user).get_accessible_fields(
            terminal_model,
            BloomerpPermission.VIEW
        ))
    
    else:
        return application_fields_to_filter_field_groups(
            ApplicationField.get_for_model(terminal_model)        
        )    
    
    


FOREIGN_ADVANCED = LookupDefinition(
    id="foreign_advanced",
    label="Advanced",
    expressions=(),
    description="Delegates the remaining lookup path to the related model.",
    nested=True,
    nested_fields_factory=_nested_fields
)
