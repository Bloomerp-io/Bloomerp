# Request scenarios

`RequestScenario` is the shared server-side HTTP contract used by
`BloomerpViewTestCase` and `BloomerpComponentTestCase`. It describes one Django
test-client request and its expected response without involving a browser.

## Basic scenario

```python
from bloomerp.tests.base import ExpectedResult, RequestScenario


RequestScenario(
    name="Returns the search results fragment",
    method="GET",
    query_params={"query": "Acme"},
    expected=ExpectedResult(
        status_code=200,
        response_validators=lambda response: "Acme" in response.content.decode(),
    ),
)
```

The default method is `GET` and the default expected status is `200`. Configure
`data`, `query_params`, `view_kwargs`, `headers`, `content_type`, and `follow`
as needed. `content_type` is only valid for methods with a request body.

Set `user` to authenticate that request. A scenario without a user is executed
logged out, even if the preceding scenario used an authenticated user.

`prepare` receives the scenario immediately before the request. Use it for
fixtures or values that must be created lazily:

```python
RequestScenario(
    name="Creates a folder",
    method="POST",
    user=self.admin_user,
    data={"name": "Contracts"},
    prepare=lambda scenario: scenario.data.update(
        {"workspace": str(self.workspace.pk)}
    ),
    expected=ExpectedResult(status_code=200),
)
```

Prefer a bound method when preparation takes more than one statement.

## Response validators

`ExpectedResult.response_validators` accepts one callable or a list. Each
validator receives the Django response and returns a boolean. The mixin also
provides reusable helpers:

- `contains_text(value)` and `does_not_contain_text(value)`
- `contains_div(value)`
- `is_json()` and `key_in_json(key)`
- `json_exact(value)` and `json_key_equals(key, value)`
- `header_equals(name, value)`
- `redirects_to(url)`

Helpers can be mixed with custom validators:

```python
expected=ExpectedResult(
    status_code=200,
    response_validators=[
        self.is_json(),
        self.json_key_equals("status", "ok"),
    ],
)
```

## Route overrides and isolation

Use `view_name` on a scenario to target another compatible registered route
from the same test class. `ModelRequestScenario` and `ModuleRequestScenario`
can select a model or module route context for one scenario.

Each scenario runs in an atomic block that is rolled back afterward, and the
test client is logged out in cleanup. This prevents database writes and login
state from leaking between scenarios.

Use request scenarios for status codes, redirects, JSON, fragments, headers,
permissions, and other server-side behavior. Use an
[end-to-end test](e2e-test-case.md) when JavaScript or real browser behavior is
part of the contract.
