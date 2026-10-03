# Model Context Protocol (MCP)

Bloomerp exposes router-registered tools and resources through a single `POST /mcp`
endpoint on the Django/Daphne service. Tools perform operations under the caller's
identity; resources provide reference material such as policy authoring guides and
workflow node documentation.

## Developer guides

- [Registering MCP tools](../router/index.md#mcp-tools): attach `McpTool` to an API
  route or register a tool without an individual HTTP URL.
- [Registering MCP resources](resources.md): use `router.register(...)` with
  `McpResource` or `McpResourceTemplate`, define readers, and enforce access rules.
- [Browser navigation](browser-tools.md): discover available pages and connected
  tabs, then navigate one tab or all of the caller's connected tabs.

## Connecting a client

Configure the client, such as VS Code, to use your instance's `/mcp` endpoint.
Requests must include `Content-Type: application/json` and
`Accept: application/json, text/event-stream`. Authenticate using an
instance-supported credential, such as a bearer API key when API keys are enabled,
or the instance's OAuth account-linking flow when configured.

The transport supports `initialize`, `ping`, `tools/list`, `tools/call`,
`resources/list`, `resources/templates/list`, `resources/read`, and notifications.
It returns JSON responses without MCP sessions or SSE; `GET /mcp` returns `405`.
Resource reads and tool calls require authentication. When OAuth is enabled,
clients can discover catalog metadata before account linking.

Registration does not grant access to models, objects, or fields. Readers and
views must enforce the caller's permissions using the normal Bloomerp services.
Reconnect the client after adding registrations so it refreshes its capabilities
and catalogs.
