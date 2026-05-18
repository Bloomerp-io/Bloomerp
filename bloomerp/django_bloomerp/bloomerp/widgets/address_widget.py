import json

from django import forms
from pycountries.countries import Country


ADDRESS_COMPONENTS = (
    ("street_1", "Address line 1", "street-address"),
    ("street_2", "Address line 2", "address-line2"),
    ("postal_code", "Postal code", "postal-code"),
    ("city", "City", "address-level2"),
    ("state", "State / Region", "address-level1"),
    ("country", "Country", "country-name"),
)

COUNTRY_CHOICES = [("", "Select a country")] + [
    (country.alpha_2, country.name)
    for country in sorted(Country, key=lambda item: item.name)
]


class AddressWidget(forms.MultiWidget):
    template_name = "widgets/address_widget.html"

    def __init__(self, attrs=None):
        widgets = []
        for key, label, autocomplete in ADDRESS_COMPONENTS:
            widget_attrs = {
                "class": "input w-full",
                "placeholder": label,
                "autocomplete": autocomplete,
                "data-address-component": key,
            }
            if key == "country":
                widget_attrs["class"] = "select w-full"
                widgets.append(forms.Select(attrs=widget_attrs, choices=COUNTRY_CHOICES))
            else:
                widgets.append(forms.TextInput(attrs=widget_attrs))

        super().__init__(widgets=widgets, attrs=attrs)

    def decompress(self, value):
        if not value:
            return [""] * len(ADDRESS_COMPONENTS)

        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                value = {}

        if not isinstance(value, dict):
            value = {}

        return [value.get(key, "") for key, _label, _autocomplete in ADDRESS_COMPONENTS]

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["address_fields"] = [
            {
                "key": key,
                "label": label,
                "subwidget": subwidget,
            }
            for (key, label, _autocomplete), subwidget in zip(
                ADDRESS_COMPONENTS,
                context["widget"]["subwidgets"],
            )
        ]
        return context
