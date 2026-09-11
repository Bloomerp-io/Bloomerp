# Component test cases

Use `BloomerpComponentTestCase` for routed Bloomerp components, including HTMX
endpoints that return fragments. It uses the same `RequestScenario` contract as
view tests and includes Bloomerp's database-backed test fixtures.

## Generated skeleton

```python
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestQrCodeComponent(BloomerpComponentTestCase):
    view_name = "components_forms_qr_code"

    def get_test_scenarios(self) -> list[RequestScenario]:
        return []
```

Add one scenario per meaningful server-side component interaction:

```python
RequestScenario(
    name="Renders a QR code fragment",
    query_params={"value": "https://example.test"},
    expected=ExpectedResult(
        status_code=200,
        response_validators=[
            self.contains_text("<svg"),
            self.does_not_contain_text("Traceback"),
        ],
    ),
)
```

See [request scenarios](request-test-case.md) for authentication, methods,
payloads, preparation hooks, validators, and transaction isolation.

## Component boundary

A component test owns the endpoint contract: request parsing, permission
checks, response status, headers, and returned HTML or JSON. A widget test may
assert that markup points to this component. An end-to-end test should be used
only when the browser must prove that an event fires, the component request is
sent, and the result is swapped into the page.

Keep direct rendering logic that does not require a request in a focused unit
test. Keep multi-page workflows and JavaScript behavior in
[end-to-end tests](e2e-test-case.md).
