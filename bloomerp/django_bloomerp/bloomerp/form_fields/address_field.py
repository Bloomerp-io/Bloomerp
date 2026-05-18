import json

from django import forms

from bloomerp.widgets.address_widget import (
    ADDRESS_COMPONENTS,
    COUNTRY_CHOICES,
    AddressWidget,
)
from pycountries.countries import Country


COUNTRY_CODES = {country.alpha_2 for country in Country}
COUNTRY_NAMES_BY_CODE = {country.alpha_2: country.name for country in Country}


class AddressValue(dict):
    def __str__(self) -> str:
        parts = []

        street_1 = self.get("street_1", "")
        street_2 = self.get("street_2", "")
        postal_code = self.get("postal_code", "")
        city = self.get("city", "")
        state = self.get("state", "")
        country_code = self.get("country", "")

        if street_1:
            parts.append(street_1)

        if street_2:
            parts.append(street_2)

        locality_parts = [part for part in [postal_code, city] if part]
        if locality_parts:
            parts.append(" ".join(locality_parts))

        if state:
            parts.append(state)

        if country_code:
            parts.append(COUNTRY_NAMES_BY_CODE.get(country_code, country_code))

        return ", ".join(parts)

def normalize_address_value(value):
    if value in forms.Field.empty_values:
        return None

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            value = json.loads(stripped)
        except (TypeError, ValueError):
            raise forms.ValidationError("Enter a valid address.")

    if not isinstance(value, dict):
        raise forms.ValidationError("Enter a valid address.")

    normalized = {}
    for key, _label, _autocomplete in ADDRESS_COMPONENTS:
        raw = value.get(key, "")
        if raw in forms.Field.empty_values:
            normalized[key] = ""
            continue
        cleaned = str(raw).strip()
        if key == "country":
            cleaned = cleaned.upper()
            if cleaned and cleaned not in COUNTRY_CODES:
                raise forms.ValidationError("Select a valid country.")
        normalized[key] = cleaned

    if not any(normalized.values()):
        return None

    return AddressValue(normalized)

class AddressFormField(forms.MultiValueField):
    widget = AddressWidget

    def __init__(self, *args, **kwargs):
        kwargs.pop("encoder", None)
        kwargs.pop("decoder", None)
        fields = []
        for key, _label, _autocomplete in ADDRESS_COMPONENTS:
            if key == "country":
                fields.append(
                    forms.ChoiceField(
                        required=False,
                        choices=COUNTRY_CHOICES,
                    )
                )
            else:
                fields.append(forms.CharField(required=False))
        kwargs.setdefault("require_all_fields", False)
        kwargs.setdefault("widget", AddressWidget())
        super().__init__(fields=fields, *args, **kwargs)

    def compress(self, data_list):
        if not data_list:
            return None

        value = {
            key: (data_list[index] if index < len(data_list) else "")
            for index, (key, _label, _autocomplete) in enumerate(ADDRESS_COMPONENTS)
        }
        normalized = normalize_address_value(value)
        if self.required and normalized is None:
            raise forms.ValidationError("Enter an address.")
        return normalized

    def to_python(self, value):
        if isinstance(value, dict) or isinstance(value, str):
            return normalize_address_value(value)
        return super().to_python(value)
