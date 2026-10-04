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

## Current user

The read-only `get_current_user` tool (display title `GetCurrentUser`) accepts no
arguments and returns the authenticated caller's `id`, `email`, `first_name`,
`last_name`, and `username`. It requires authentication and no model permissions.

## Model identities for assistant tools

Shared object and model artifacts identify models with Django's `model_label`,
such as `sales.Customer`. Use that same label in all three assistant tools:

- `api_assistant_mutation_catalog`: optionally filter by `model_label`. Each
  catalog entry returns its `model_label`; relation fields use
  `related_model_label` to identify their target model.
- `api_assistant_object_retrieve`: supply `model_label` and `object_id` to read
  the object's current permitted fields.
- `api_assistant_mutations`: supply `model_label`, `operation`, and the appropriate
  `object_id` and/or `data` to create, partially update, or delete an object.

For example, an object artifact with `model_label: sales.Customer` can be used
directly in an update:

```json
{
  "model_label": "sales.Customer",
  "operation": "update",
  "object_id": "42",
  "data": {"email": "new@example.com"}
}
```

Model-label matching is case-insensitive; responses use the model's canonical
Django label. Only models exposed by the generated API can be resolved, and the
generated API continues to enforce row and field permissions.

The former `resource` inputs and `related_resource` metadata are removed. Clients
must refresh their tool schemas and send model labels instead of plural resource
keys. Generated REST URLs keep their existing paths. Pending agent runs pinned
to the previous tool contracts must be restarted after this change.

## Uploading and linking files

Two tools handle files without discovering internal content-type IDs:

- `api_assistant_file_upload` accepts `filename` and `content_base64`. Omit a
  destination to upload into the general file library, or supply `model_label`
  and `object_id` to attach directly to an object's files. The REST endpoint at
  `POST /api/files/upload/` also accepts a multipart `file` instead of base64.
- `api_assistant_file_link` accepts an existing `file_id` and a destination.
  Use this for file artifacts already attached to a chat; their bytes are already
  uploaded. Repeating the same link does not create another file.

Both accept `folder_id`. An object-scoped folder supplies its object identity;
if an explicit object is also provided, the folder must belong to that object.
Object destinations without a folder use the object's automatic file folder.
Model/module organizational folders cannot receive files without an object;
use an object folder or a folder in the general library.

Files have one object owner and one folder. Linking replaces the old placement
rather than copying bytes or creating multiple owners. Canonical field-owned
files (for example a résumé field) must be managed through that field instead.
Source access and destination row/field permissions are checked independently.

Uploads use the existing `BLOOMERP_AGENT_UPLOAD_MAX_BYTES` limit (20 MiB by
default). Both tools return only `file_id`, `name`, `model_label`, `object_id`,
and `folder_id`. They use the normal MCP mutation approval flow.
