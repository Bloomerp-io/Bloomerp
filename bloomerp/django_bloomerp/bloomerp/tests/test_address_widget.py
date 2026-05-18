from django.http import QueryDict
from django.test import SimpleTestCase

from bloomerp.widgets.address_widget import AddressWidget


class TestAddressWidget(SimpleTestCase):
    def test_decompress_returns_values_in_component_order(self):
        widget = AddressWidget()

        values = widget.decompress(
            {
                "street_1": "Main street 1",
                "postal_code": "1000",
                "city": "Brussels",
                "country": "Belgium",
            }
        )

        self.assertEqual(
            values,
            ["Main street 1", "", "1000", "Brussels", "", "Belgium"],
        )

    def test_country_widget_is_select_with_iso_choice_values(self):
        widget = AddressWidget()

        country_widget = widget.widgets[-1]

        self.assertEqual(country_widget.__class__.__name__, "Select")
        self.assertIn(("BE", "Belgium"), list(country_widget.choices))

    def test_value_from_datadict_collects_component_values(self):
        widget = AddressWidget()
        data = QueryDict("", mutable=True)
        data.update(
            {
                "office_address_0": "Main street 1",
                "office_address_1": "",
                "office_address_2": "1000",
                "office_address_3": "Brussels",
                "office_address_4": "",
                "office_address_5": "BE",
            }
        )

        value = widget.value_from_datadict(data, {}, "office_address")

        self.assertEqual(
            value,
            ["Main street 1", "", "1000", "Brussels", "", "BE"],
        )
