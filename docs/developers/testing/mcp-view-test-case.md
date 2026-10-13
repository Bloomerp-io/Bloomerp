# MCP view test cases

Use `BloomerpMcpViewTestCase` for MCP-only tools and resource readers. These
registrations have no individual HTTP URL. The base sends JSON-RPC requests
through the real `/mcp` transport and verifies the registration in the matching
tool, resource, or resource-template catalog.

The `views` generator category selects this base for `mcp` and `mcp_resource`
routes. Generated files mirror their source directory under `tests/views/`.
HTTP API routes that also expose MCP metadata keep their existing API test base;
you can add an MCP test class to cover their transport contract separately.

```bash
cd bloomerp/django_bloomerp
uv run python manage.py generate_test_cases bloomerp --functionality=views --dry-run
```

## Tool scenarios

```python
from bloomerp.tests.base import (
    BloomerpMcpViewTestCase,
    ExpectedResult,
    McpRequestScenario,
)


class TestGetContentTypeView(BloomerpMcpViewTestCase):
    """Verify model-label resolution through MCP."""

    view_name = "get_content_type"

    def get_test_scenarios(self) -> list[McpRequestScenario]:
        """Describe valid and invalid content-type lookup requests."""
        return [
            McpRequestScenario(
                name="Resolves an installed model label",
                user=self.normal_user,
                arguments={"model_label": "contenttypes.ContentType"},
                expected=ExpectedResult(
                    response_validators=self.mcp_is_error(False),
                ),
            ),
            McpRequestScenario(
                name="Rejects an unknown model label",
                user=self.normal_user,
                arguments={"model_label": "missing.Model"},
                expected=ExpectedResult(
                    response_validators=self.mcp_is_error(),
                ),
            ),
        ]
```

The base supplies `admin_user` and `normal_user`, with no dynamic customer models.
`McpRequestScenario` extends `RequestScenario`: preparation, cleanup, per-scenario
authentication, headers, response validators, and database rollback behave as
described in [request scenarios](request-test-case.md). Preparation runs before
arguments are encoded, so it can populate `scenario.arguments` with fixture IDs.
A scenario without `user` runs logged out.

Use `arguments` for tool inputs rather than HTTP `data` or `query_params`. The base
selects `tools/call`, adds the tool name, and sends a JSON request with the required
Accept and protocol-version headers. `view_name` can select another MCP registration
for a scenario. The transport method must remain `POST`.

## Resource scenarios

For a resource reader, the base selects `resources/read`. Concrete resources supply
their registered URI automatically. Templates fill and URL-encode their variables
from `arguments`. Set `uri` explicitly to test another URI, including missing or
invalid resource addresses.

Use `mcp_resource_text_equals(expected)` for a single text resource. For binary or
JSON resources, write a named response validator that inspects
`response.json()["result"]["contents"]`.

## Response assertions

`ExpectedResult.status_code` refers to the HTTP transport status. MCP failures
often return HTTP 200, so assert their envelope as well:

- `mcp_is_error(True)` checks a tool execution or input-validation error.
- `mcp_is_error(False)` checks a successful tool outcome.
- `mcp_structured_content_equals(expected)` checks a successful tool's exact payload.
- `mcp_rpc_error(code)` checks a JSON-RPC error, including resource access errors.
- `mcp_resource_text_equals(expected)` checks a single resource text payload.

The usual `RequestTestCaseMixin` JSON and header helpers are also available.
Anonymous transport behavior depends on whether OAuth is enabled: tool calls may
return an MCP account-linking error with HTTP 200, or an HTTP authentication error.
Set explicit expectations for the configuration your test exercises.
