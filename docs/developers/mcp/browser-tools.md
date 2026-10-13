# Browser navigation through MCP

The authenticated base page starts `BloomerpAgent` from the main TypeScript bundle.
It connects to `/ws/agents/<tab_id>/` using the browser's login session and reports
its URL, title, focus, and page version. MCP requests use the linked MCP user's
identity. Both sessions must belong to the same Bloomerp user.

## Try it from your MCP client

1. Run Bloomerp with its ASGI application, such as the project's Daphne-backed
   `python manage.py runserver`. HTTP and websockets must reach the same instance.
2. Open Bloomerp in a browser and sign in. Reload the page after updating the
   frontend bundle. Reconnect the MCP client so it refreshes its tool catalog.
3. Call `view_pages` with `{"search": "customer"}` or `{}` to browse all matches.
   The result includes `pages` with usable URLs and `browser_tabs` with target IDs.
4. Call `navigate_user_mcp` using a returned URL and tab ID:

   ```json
   {
     "url": "/replace-with-a-returned-page-url/",
     "tab_id": "replace-with-a-returned-tab-id"
   }
   ```

Omit `tab_id` to navigate all connected tabs and devices belonging to your user.
Provide `tab_id` to navigate one specific tab. A useful agent prompt is: “Find the
customer list page and navigate all my connected Bloomerp tabs to it.”

`accepted` means the browser acknowledged navigation before leaving the current
page. `dispatched` means the acknowledgement timed out, so loading is unconfirmed.
`failed` reports a browser error, such as a stale page version. Navigation performs
a full page load and preserves query strings and fragments. The destination view
enforces its normal permissions.

The response contains `results` with a status, command ID, and result for each
targeted connection. Top-level `success` means no connection reported failure;
acknowledgement timeouts remain `dispatched`, not confirmed navigation. `partial`
means some connections failed while others accepted or were dispatched. If every
connection fails, the MCP call returns an error. No connected targets also returns
a clear error.

## Scope and troubleshooting

- `view_pages` searches searchable UI routes, respects available view permission
  gates, and excludes routes requiring path arguments. Filters include `module`
  (module ID), `model` (`app.Model`), `route_type`, `page`, and `page_size`.
- Browser discovery probes live user-scoped websocket connections through the
  channel layer. It does not depend on a process-local presence cache.
- The default in-memory channel layer works in one ASGI process. Separate workers
  require a shared layer such as the production Redis configuration.
- If no browser tabs appear, check the user identity, websocket connection, and
  that the page includes `data-bloomerp-agent="enabled"`. The bridge is available
  as `window.bloomerpAgent` for debugging.
- Duplicated browser tabs can copy their session-storage identity. Broadcasting
  reaches each connection individually; explicit selection rejects duplicate IDs.
  Open an independent tab for a unique target ID in this initial implementation.
- Highlight/click handlers and the chat runner remain future integrations.

## Validation

Backend tests exercise real MCP dispatch and the Channels consumer together,
including acknowledgements, user isolation, explicit tab selection, URL validation,
permission gates, and origin checks. Frontend tests exercise base-page startup and
navigation guards with a simulated browser/socket.
