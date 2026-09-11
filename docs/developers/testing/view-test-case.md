# View test cases

Use the Bloomerp view test bases for routed server-side views and APIs. The
generator selects the base class that matches the route type and adds the
route context required to resolve it.

## Generated skeleton

```python
from bloomerp.tests.base import (
    BloomerpAPIViewTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestAccessibleTablesView(BloomerpAPIViewTestCase):
    view_name = "api_sql_accessible_tables"

    def get_test_scenarios(self) -> list[RequestScenario]:
        return []
```

The base always verifies that exactly one matching route is registered. Add
request scenarios for the callable's behavior:

```python
def get_test_scenarios(self) -> list[RequestScenario]:
    return [
        RequestScenario(
            name="Returns accessible tables as JSON",
            user=self.admin_user,
            expected=ExpectedResult(
                status_code=200,
                response_validators=[self.is_json(), self.key_in_json("tables")],
            ),
        )
    ]
```

See [request scenarios](request-test-case.md) for request data, preparation,
authentication, response validators, and isolation.

## Route-specific bases

The generator chooses among:

- `BloomerpViewTestCase` for application routes
- `BloomerpModelViewTestCase` for model routes
- `BloomerpDetailViewTestCase` for object-detail routes
- `BloomerpModuleViewTestCase` for module routes
- `BloomerpAPIViewTestCase` for application API routes
- `BloomerpAPIModelViewTestCase` for model API routes
- `BloomerpAPIDetailViewTestCase` for detail API routes

Model and detail bases require a `model`. Module bases require a registered
module object or ID. Generated files fill these values when discovery can
identify one unambiguously; otherwise they leave the value as `None` for the
developer to select.

For detail routes, override `create_test_object()` to provide the default
object. The base then supplies its primary key as the default route keyword
arguments. Override `get_view_kwargs()` when a route uses different arguments.

Use `ModelRequestScenario(model=...)` or `ModuleRequestScenario(module=...)`
when individual scenarios need a different route context from the class
default.

Keep browser-only behavior out of this layer. A view scenario should validate
the response caused by one HTTP request; an end-to-end scenario should validate
the user's interactive journey.
