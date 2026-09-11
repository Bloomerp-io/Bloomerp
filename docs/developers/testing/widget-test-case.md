# Widget test cases

Use `BloomerpWidgetTestCase` for server-side behavior of custom Django widgets.
Widgets do not share a create-update-delete lifecycle, so `WidgetScenario`
contains an ordered list of flexible `WidgetOperation` objects.

This layer covers widget construction, context, rendering, decompression, and
submitted-value extraction. It does not replace request tests for HTMX
endpoints or end-to-end tests for real browser interaction.

## Generated skeleton

```python
from bloomerp.widgets.address_widget import AddressWidget
from bloomerp.tests.base import (
    BloomerpWidgetTestCase,
    ExpectedWidgetException,
    WidgetOperation,
    WidgetScenario,
)


class TestAddressWidget(BloomerpWidgetTestCase[AddressWidget]):
    widget_class = AddressWidget

    def get_test_scenarios(self) -> list[WidgetScenario[AddressWidget]]:
        return []
```

The base always confirms that the configured class is a Django widget and has
a template. Each scenario then constructs a fresh widget.

## Scenarios and operations

Constructor positional and keyword arguments may be eager values or
zero-argument factories. Arbitrary objects are accepted, including model
classes for widgets such as `ForeignFieldWidget(model=Todo)`.

`preparation` runs before constructor arguments are resolved.
`post_construction` and `constructor_validators` receive the widget instance.
Each operation receives the same widget, returns a result, and validates that
result with one lambda or a list.

```python
WidgetScenario(
    name="Address values are decompressed in component order",
    operations=[
        WidgetOperation(
            name="decompress",
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
)
```

Operations execute in declaration order. Prefer lambdas for one expression and
named bound methods when building submitted data or checking a complex result
would be clearer as statements.

## Expected exceptions

Attach `ExpectedWidgetException` directly to the operation expected to fail.
It accepts an exception class or tuple and an optional message regex. Do not
configure result validators on an operation expected to raise. The scenario
stops after the expected exception.

## HTMX and browser behavior

Use this base to verify that rendered HTML contains the intended HTMX URL,
trigger, target, and swap attributes. Test the endpoint response, permissions,
and returned fragment with a component or request scenario. Use an end-to-end
test only when browser wiring matters: an event fires, a request is sent, and
the returned markup is swapped into the page.

The base is database-free. A widget may accept a model class without querying
the database, but operations that resolve content types or load model instances
need a database-enabled specialized test rather than silently adding database
access to every widget scenario.
