# Registering MCP resources

Bloomerp ships two authenticated authoring references. Their Python readers live
directly in `bloomerp/views/mcp/authoring_references.py` and are discovered through
the router's existing views discovery. Their Markdown documentation lives in
`bloomerp/views/mcp/resources/`:

- `bloomerp://guides/create-workflow` (`application/json`) includes a construction
  guide and every current `WORKFLOW_NODE_REGISTRY` definition. Parameters come
  from declared configuration form fields. Reads never instantiate forms,
  executors or workflows, evaluate callable defaults, or enumerate model/dynamic
  choices. Declared IO schemas and ports are baseline metadata; the editor owns
  configuration-dependent additions. The guide documents the graph save API and
  the current absence of a dedicated create-workflow MCP tool.
- `bloomerp://guides/create-policy` (`text/markdown`) explains the nested policy
  API, global/row/field grants and separate user/group assignment. Permission
  actions and the row-rule schema are generated from current definitions.

These resources contain authoring metadata, not saved workflow configurations,
policy assignments or object choices. Reading a guide does not grant authority
to perform the mutations it describes. Packaged Markdown files are included in
the distribution's package data.

Use the existing `router.register(...)` decorator with an `McpResource` or
`McpResourceTemplate` contract. The router infers `route_type="mcp_resource"`;
you can also supply that route type explicitly.

Place Python resource readers directly in an installed app's `views/mcp/`
directory and Markdown documentation in its `views/mcp/resources/` directory.
The existing router discovers the views automatically; the documentation
directory contains no Python providers. Include the Markdown files in package
data when distributing the app.

## A packaged Markdown guide

```python
from pathlib import Path

from django.http import HttpRequest

from bloomerp.mcp.definition import McpResource
from bloomerp.router import router


@router.register(
    name="Create policy guide",
    description="Explain how to construct and assign a Bloomerp policy.",
    route_type="mcp_resource",
    mcp=McpResource(
        uri="bloomerp://guides/create-policy",
        mime_type="text/markdown",
    ),
)
def create_policy_guide(request: HttpRequest) -> str:
    """Read the packaged policy authoring guide for the authenticated caller."""
    path = Path(__file__).parent / "resources" / "create-policy.md"
    return path.read_text(encoding="utf-8")
```

The router's name and description provide the catalog metadata. The contract can
optionally override `title` and `description`. Resource identity is the URI, not
the route name. A duplicate URI is rejected unless `override=True` replaces it.

## A generated reference template

```python
from django.http import HttpRequest

from bloomerp.automation.registry import WORKFLOW_NODE_REGISTRY
from bloomerp.mcp.definition import McpResourceTemplate
from bloomerp.router import router


@router.register(
    name="Workflow node reference",
    description="Read the installed workflow node's identity and description.",
    mcp=McpResourceTemplate(
        uri_template="bloomerp://reference/workflow-nodes/{subtype}",
        mime_type="application/json",
    ),
)
def workflow_node_reference(request: HttpRequest, subtype: str) -> dict[str, str]:
    """Describe one installed workflow node without executing it."""
    from django.http import Http404

    node = WORKFLOW_NODE_REGISTRY.get(subtype)
    if node is None:
        raise Http404("Unknown workflow node")
    return {
        "id": node.id,
        "type": node.type,
        "name": str(node.name),
        "description": str(node.description),
    }
```

This example returns basic node metadata; a full authoring reference can also
generate parameters and port contracts from its executor and configuration form.

Templates currently support simple RFC 6570 `{name}` variables with unique
identifier names. Each captures one nonempty URI segment and is percent-decoded
before being passed as a named string argument to the reader. The `request`
variable is reserved. Encoded separators, control characters, and `.`/`..` values
are rejected. Other expressions, such as `{+path}` and `{?query}`, are unsupported
and rejected at registration time.

An optional `parameter_schema` JSON Schema (or schema factory) validates the
decoded string arguments, including enum constraints. Concrete resources take
precedence over templates. Equivalent templates with renamed variables are
duplicate registrations; other overlapping matches produce an ambiguity error.

## Readers and access

Readers receive a GET request with the original user's identity, authentication
token, host, and HTTPS state. Function readers receive template arguments as
keyword parameters. Class readers must support GET; arguments are also passed to
their GET handler.

Return a string for textual content, bytes for base64-encoded binary content, or a
dictionary/list for JSON text. Django `HttpResponse` and DRF `Response` results
are also supported. Declare the content type using `mime_type`.

Reads always require authentication. Enforce any additional model, object, or
field permissions in the reader, using the existing Bloomerp permission services.
Raise `PermissionDenied` to reject access or `Http404` for a missing resource.
OAuth-enabled clients may discover catalog metadata before account linking;
discovery never calls the readers.

Resource registrations have no HTTP paths and cannot be searchable UI routes.
They are excluded from `tools/list`, HTTP URL patterns, and websocket patterns.

## MCP operations

- `initialize` advertises `resources: {}` alongside tools.
- `resources/list` returns concrete resource metadata.
- `resources/templates/list` returns template metadata.
- `resources/read` accepts a `uri` and returns one content entry.

For example, read a template using:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "resources/read",
  "params": {
    "uri": "bloomerp://reference/workflow-nodes/SEND_EMAIL"
  }
}
```

Catalogs currently return all registrations without pagination. Subscriptions,
completion, and change notifications are not advertised. Reconnect your MCP client
after adding providers to refresh its discovered capabilities and catalogs.

## Built-in AI agents

The agent configuration form lists resources separately from tools, with all or
selected resource access. Selections use concrete URIs or URI templates; an
empty selected list permits no resources. Existing agents default to all
resources. Acting-user authentication and reader permissions continue to apply.

Tool-calling models discover allowed resources as read-only reader tools. The
bridge calls `resources/read` and returns embedded resource content, including
its URI and MIME type. Template parameters follow the registered parameter
schema. This adaptation is local to the agent runtime: resources remain absent
from the public MCP `tools/list` response. External integration catalogs currently
expose tools only; their resources are not included in these built-in selectors.
