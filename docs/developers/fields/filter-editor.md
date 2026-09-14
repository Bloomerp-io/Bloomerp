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

### Permission rules

The permission table reuses `FilterWidget` with model scope from its ContentType.
Each table entry stores one `Filter` group in `RowPolicyRule.rule`, with its own
AND/OR connector and any number of conditions. **Add condition** edits that
group; adding another table entry creates a separate grant. Applicable grants
retain the existing OR combination. **Add group** is therefore absent inside
this entry editor. Legacy field IDs/operators are normalized at the backend boundary.
The table uses `include_controls=False`: no name, Save, Clear, Apply, or Select
controls are rendered. **Use rule** updates the draft table, and the existing
permission workflow submits it.

`FilterWidget(include_controls=False)` emits `data-include-controls="false"`.
The default is true. Without outer controls, the hidden grouped JSON updates on
edits, and an enclosing form can submit without an Apply event. Incomplete edits
clear the hidden value and block submission; condition/group editing remains
available within the configured group limit.

### Saved presets

`SavedFilter` is the Django record; `bloomerp.filters.definition.Filter`
remains one grouped condition definition. A preset contains a name, scope,
identifier, and grouped JSON. Names are unique within a scope/identifier pair.
Scope access is shared; there is no private owner or default-filter relationship.

- GET `components/filters/get?scope=model&identifier=<ContentType ID>`
  lists full preset payloads for exactly that authorized scope. Workspaces use
  `scope=workspace&identifier=<Workspace ID>`.
- POST `components/filters/save` accepts JSON containing `scope`,
  `identifier`, `name`, and `filters`. Omit `filter_id` to create a record
  (201). Include it to update that exact scoped record (200). An ID from another
  scope or identifier is rejected; updates never move records.

Saving validates grouped JSON, referenced fields, lookups, values, and existing
filter permissions. Saving does not change defaults or apply the filter.
The blue **Select** button opens a separate overlay under `document.body`,
positioned against the button, and fetches the scoped list. It does not resize
the parent filter popover. Choosing an item loads it locally and closes the menu, without a second
endpoint request. Editing keeps its ID, so subsequent saves update it.
The flyout starts with a name search, an **Add filter** action, and a divider,
followed by matching saved filters. Search ignores case. **Add filter** clears
the saved identity and name, starts an empty condition group, and focuses the
name input; Save then creates a new preset. Apply emits optional
`filter_id` and `filter_name` alongside the grouped filters; it does not save.

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
