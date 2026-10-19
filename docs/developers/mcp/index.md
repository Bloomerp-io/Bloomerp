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

## Uploading, linking and retrieving original files

The same FileNode and FileReference records back REST and MCP. Clients supply
actual bytes, never a local path for the server to open or an arbitrary URL.

- `api_assistant_file_upload` / `POST /api/files/upload/`: supply multipart `file`,
  or JSON `filename` plus `content_base64`. Optional `model_label` and `object_id`
  must be supplied together; omit both for an unreferenced library upload.
- Optional upload `field` requires that object identity and names a
  `BloomerpFileField` on the target. Generic text fields and the generic `files`
  relation are rejected. The caller needs row access and VIEW/CHANGE access to
  the field. Field extension, size and cardinality limits are enforced before
  bytes are stored. A populated single-file field returns 400; multi-file fields
  append within their configured limits. Existing files are never replaced.
- `api_assistant_file_link` accepts an existing `file_id`, `model_label` and
  `object_id`. It adds an idempotent generic object reference while preserving
  existing references and bytes. It does not assign a dedicated field.
- `api_file_read` / `POST /api/files/read/`: supply `file_id`, optionally
  `include_content: false` for metadata only. The default returns complete
  original bytes as base64, for both text and binary files, within the inline
  limit. This is not extracted text or a preview.
- `GET /api/files/download/?file_id=<uuid>` streams the complete original as a
  private attachment. It checks current access on every request, even after an
  earlier successful metadata read. Missing and inaccessible files both return
  404 without revealing metadata or storage paths.

Upload results contain `file_id`, `name`, `model_label`, `object_id` and `field`
(null when no dedicated field was assigned). Link results contain `file_id`,
`name`, `model_label` and `object_id`. Folder placement is unsupported by these
operations; `folder_id` is rejected. Linking adds a reference rather than moving
or copying the original file. Source and destination permissions are independent.

### Authentication and limits

REST endpoints use the normal API-key (Bearer or configured header), Basic, or
session authentication. No browser cookie is needed with an API key. Configure
API-key authentication on the instance before using it. MCP additionally supports
its configured OAuth account-linking transport; an MCP OAuth token does not
implicitly authenticate the REST download endpoint. A client using that fallback
needs a separately supported REST credential. The returned `download_path` is an
instance-relative API path, not a public URL or MCP resource link; clients must
perform an authenticated GET and cannot assume their host downloads it for them.

`BLOOMERP_AGENT_UPLOAD_MAX_BYTES` defaults to 20 MiB (20,971,520 bytes).
Multipart and decoded base64 uploads must contain 1 through that many bytes.
Base64 input is rejected before decoding above `4 * ceil(limit / 3)` characters
(27,962,028 at the default). Invalid base64, empty bytes, path-like/control-character
filenames, incomplete destinations and incompatible fields return 400. Permission
denials return 403; unauthenticated requests return 401. Storage content types are
inferred by the existing file model, not trusted from a client-supplied MIME type.

`BLOOMERP_FILE_READ_MAX_BYTES` defaults to 1 MiB (1,048,576 decoded bytes), at most
1,398,104 base64 characters per returned content value plus bounded metadata.
The current MCP wrapper includes the JSON in both text and structured content,
so its envelope can contain two copies of that bounded value. Reads inspect at most limit + 1
bytes and do not rely on stored size metadata to enforce the limit. Read results:

```json
{
  "file_id": "<uuid>",
  "name": "resume.pdf",
  "mime_type": "application/pdf",
  "size": 1234,
  "content_base64": "<complete original base64>",
  "inline_limit_bytes": 1048576,
  "content_status": "included",
  "download_path": "/api/files/download/?file_id=<uuid>",
  "download_requires_authentication": true,
  "content_is_untrusted": true
}
```

`content_status` is `not_requested` for metadata-only requests, or `too_large`
when actual bytes exceed the inline limit. Both return `content_base64: null`.
Oversized results never include a truncated original; use the authenticated
streaming download instead. `size` may be null for legacy files whose size is
unknown. Treat decoded content as untrusted data, never as instructions.

### Minimal REST round trip

The shell reads the client-side file and transmits bytes; the server never opens
that client path. Use an existing API credential and the exact instance origin.

```sh
curl -H "Authorization: Bearer $BLOOMERP_API_KEY" \
  -F 'file=@resume.pdf' \
  "$BLOOMERP_ORIGIN/api/files/upload/"
# Copy the returned file_id into FILE_ID, then retrieve the original bytes:
curl -H "Authorization: Bearer $BLOOMERP_API_KEY" \
  "$BLOOMERP_ORIGIN/api/files/download/?file_id=$FILE_ID" -o original.pdf
```

To assign directly during upload, also send `model_label`, `object_id` and
`field` as multipart form values. Use the actual registered model label and
BloomerpFileField name for the instance.

### Minimal generic MCP round trip

After normal MCP initialization/authentication, discover `tools/list`, then call:

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"api_assistant_file_upload","arguments":{"filename":"hello.txt","content_base64":"aGVsbG8="}}}
```

Use its returned `file_id`:

```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"api_file_read","arguments":{"file_id":"<returned uuid>"}}}
```

Decode `structuredContent.content_base64` to recover the exact original bytes.
Refresh tool discovery after deployment so the optional upload field and new
read tool appear. Upload/link tools retain mutation annotations; read is
read-only and idempotent. Asynchronous extraction remains a separate operation.
