# Shared filter editor

Embed the editor using the Cotton component:

```html
<c-features.filters.container scope="model" id="{{ content_type_id }}"
    initial_filters="{{ initial_filters_json }}" />
```

Use `scope="workspace"` and the workspace ID for workspace field discovery.
`initial_filters` is a JSON-encoded list of `Filter` groups. If omitted, the
component uses the current `filter` query parameter, then defaults to `[]`.
The attribute is HTML-escaped. No field-type or lookup IDs are interpreted by
TypeScript: nested lookups and user-entered field keys follow discovery metadata.

The editor owns group/condition controls, collapse, clear, and apply. Each group
has an AND/OR selector; groups combine with implicit AND. Empty groups retain
the backend's semantics (empty AND matches all, empty OR matches none).
Applied filter chips are deferred.

`FilterContainer.getFilters()` returns canonical groups and rejects incomplete
conditions. `setFilters(groups)` restores the editor asynchronously; applying
is rejected until all condition editors finish loading. Component widgets use
`BaseWidget.setValue(value, false)` and `getValue()`. Ordinary form controls are
read directly; string coercion and lookup validation remain backend concerns.

Applying updates the hidden `filter` input and emits the bubbling event
`bloomerp:filters-apply` with `{filters, scope, id}`. Clearing edits the draft;
Apply submits that empty draft. Model dataviews consume the event and send JSON
through the `filter` query parameter. Other hosts, including the future policy
form and workspace execution adapter, can consume this event or call
`getFilters()` before submitting. The editor itself never executes SQL or
chooses which tiles to refresh.

The component is registered as `unified-filter-container`. Legacy callers of
`filter-container` keep their existing contract during migration.

Focused browser verification (requires installed frontend dependencies and
Playwright Chromium):

```sh
bloomerp/django_bloomerp/.venv/bin/python -m unittest discover \
  -s bloomerp/django_bloomerp/bloomerp/tests/e2e/filters \
  -p 'test_filter_container_e2e.py'
```

These tests exercise the real editor in Chromium with fixture component responses;
they do not replace backend component tests or the pending full view E2E suites.

### Shared workspace fields

Workspace discovery combines fields with the same name and registered FieldType
ID under **Shared fields**. Both analytics and dataview tiles participate. A
shared identity must refer to one field per tile, across at least two tiles.
Different related models or choices keep fields separate. FieldTypeDefinition
has no additional sharing attributes.

Every tile configuration accepts `filter_shared_keys`:

```python
filter_shared_keys={
    "reporting_week": "week",  # Share with other tiles' week fields.
    "internal_status": None,   # Keep this field tile-specific.
}
```

Omitted names default to the field name (the application field name for a
dataview, or the output column name for analytics). Keys must be nonempty and
cannot contain `:`. For example, four compatible `week` columns produce one
`shared:week` field. Incompatible names remain in their tile groups; existing
`tile_<id>:<field>` paths continue to resolve.

Shared primitive editors use the FieldType's default form factory. Matching
choices and relations retain the application-field context needed by their
widgets. Nested discovery exposes only compatible children available through
every participating field, after the existing access checks.

`FilterFieldResolver.resolve_all(path)` expands a shared path into the actual
field and execution target for each tile. `resolve_for_tile(path, tile_id)`
returns that tile's pair or `None` if it does not participate. `resolve(path)`
remains the editor-facing API; its representative target must not be used to
execute a shared condition for the entire workspace. Analytics renderers now use `get_filtered_query`, which projects each group to
its participating tile fields and compiles it through `compile_sql_field_filters`.
Groups with no conditions for the tile are omitted; explicitly empty AND/OR
groups preserve their true/false meaning. Dataview renderers use the same `filters_for_tile` projection before passing
local field paths to the ordinary permission-aware dataview component. Paging
and subsequent dataview requests retain these local filters.

The analytics compiler uses the shared `resolve_condition` value cleaning and
registered SQL factories. SQL stays parameterized until `get_filtered_query`
adapts it to the existing SQL executor's string interface. Legacy shorthand remains supported; canonical JSON rejects invalid fields,
lookups, and values. SQL variable substitution has been removed.

Analytics filters expose an optional `shared_key` in the builder. Leaving it blank
uses the column name (or the tile-level mapping, if configured).
