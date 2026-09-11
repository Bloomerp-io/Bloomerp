from django.http import QueryDict

from bloomerp.tests.base import BloomerpWidgetTestCase, WidgetOperation, WidgetScenario
from bloomerp.widgets.address_widget import AddressWidget


class TestAddressWidget(BloomerpWidgetTestCase[AddressWidget]):
    widget_class = AddressWidget

    def get_test_scenarios(self) -> list[WidgetScenario[AddressWidget]]:
        return [
            WidgetScenario(
                name="decompresses address components in display order",
                operations=[
                    WidgetOperation(
                        name="decompress address mapping",
                        execute=lambda widget: widget.decompress(
                            {
                                "street_1": "Main street 1",
                                "postal_code": "1000",
                                "city": "Brussels",
                                "country": "Belgium",
                            }
                        ),
                        result_validators=lambda value: value
                        == ["Main street 1", "", "1000", "Brussels", "", "Belgium"],
                    )
                ],
            ),
            WidgetScenario(
                name="uses ISO country choices",
                operations=[
                    WidgetOperation(
                        name="get country widget",
                        execute=lambda widget: widget.widgets[-1],
                        result_validators=[
                            lambda value: value.__class__.__name__ == "Select",
                            lambda value: ("BE", "Belgium") in list(value.choices),
                        ],
                    )
                ],
            ),
            WidgetScenario(
                name="collects address values from submitted data",
                operations=[
                    WidgetOperation(
                        name="read multipart submission",
                        execute=lambda widget: widget.value_from_datadict(
                            QueryDict(
                                "office_address_0=Main+street+1&office_address_1="
                                "&office_address_2=1000&office_address_3=Brussels"
                                "&office_address_4=&office_address_5=BE"
                            ),
                            {},
                            "office_address",
                        ),
                        result_validators=lambda value: value
                        == ["Main street 1", "", "1000", "Brussels", "", "BE"],
                    )
                ],
            ),
            WidgetScenario(
                name="renders filter value provider attributes",
                operations=[
                    WidgetOperation(
                        name="render address input",
                        execute=lambda widget: widget.render("office_address", None),
                        result_validators=[
                            lambda value: "data-filter-value-provider" in value,
                            lambda value: 'data-field-name="office_address"' in value,
                        ],
                    )
                ],
            ),
        ]
