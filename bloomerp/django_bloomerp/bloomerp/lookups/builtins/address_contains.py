from __future__ import annotations

from bloomerp.lookups.definition import FilterFieldContext
import json
from typing import Any

from django.core.exceptions import ValidationError
from django.db.models import Q

from bloomerp.form_fields.address_field import AddressFormField, normalize_address_value
from bloomerp.lookups.definition import CompiledLookup, LookupDefinition
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField
from bloomerp.widgets.address_widget import ADDRESS_COMPONENTS


def normalize_address(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return value if isinstance(value, dict) else {}


def address_contains_q_factory(
    application_field: ApplicationField,
    field_path: str,
    expression: str,
    value: Any,
) -> CompiledLookup:
    del application_field, expression
    normalized_value = normalize_address(value)
    if isinstance(value, str) and value.strip() and not normalized_value:
        return CompiledLookup(predicate=Q(pk__in=[]))
    predicate = Q()
    for key, _label, _autocomplete in ADDRESS_COMPONENTS:
        component = str(normalized_value.get(key, "")).strip()
        if component:
            lookup = "iexact" if key == "country" else "icontains"
            predicate &= Q(**{f"{field_path}__{key}__{lookup}": component})
    return CompiledLookup(predicate=predicate)


def address_contains(actual: Any, expected: Any) -> bool:
    actual_address = normalize_address(actual)
    expected_address = normalize_address(expected)
    if not expected_address:
        return True
    for key, _label, _autocomplete in ADDRESS_COMPONENTS:
        expected_component = str(expected_address.get(key, "")).strip()
        if not expected_component:
            continue
        actual_component = str(actual_address.get(key, ""))
        if key == "country":
            if actual_component.casefold() != expected_component.casefold():
                return False
        elif expected_component.casefold() not in actual_component.casefold():
            return False
    return True


class AddressContainsFormField(AddressFormField):
    """Clean filter payloads without requiring the address widget's list form."""

    def clean(self, value: Any) -> Any:
        if isinstance(value, (dict, str)):
            try:
                return normalize_address_value(value)
            except ValidationError:
                # Invalid legacy query parameters compile to a no-match
                # predicate instead of turning a filter request into a 500.
                return value
        return super().clean(value)


def address_contains_form_factory(
    context: FilterFieldContext,
) -> AddressFormField:
    del context
    return AddressContainsFormField(required=False)


ADDRESS_CONTAINS = LookupDefinition(
    id="address_contains",
    label="Contains",
    expressions=("address_contains", "contains"),
    q_factory=address_contains_q_factory,
    python_evaluator=address_contains,
    default_form_factory=address_contains_form_factory,
)
