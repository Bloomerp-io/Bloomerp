# Create a workspace

Understand what the user wants to see and do on the workspace. Use the live
`tile_types` names and descriptions to choose suitable tiles. Ask only for
missing user preferences, such as the workspace's name, module scope, or who
should own it. Resolve implementation details through the available tools.

## Discover the creation contract

Use `api_assistant_mutation_catalog` for the exact model labels in `models`:
`workspace` and `tile`. Check that create is available and inspect required and
writable fields. Use `api_assistant_mutations` to create the records. The
configuration schemas here describe the value of a Tile's `schema` field;
they do not replace the generated mutation contract or grant write access.
If a required model, operation or field is unavailable, explain the gap and
help the user finish in the editor. Do not assume a resource read allows HTTP
calls or that generic mutations accept nested tile creation.

Tile metadata (`name`, `description`, `icon`) belongs on the Tile model, alongside
`type` and `schema`, rather than inside `schema`. Use the exact registered key
from `tile_types[].type` for Tile.type. Shared declarative metadata such as a
native config `id` is intentionally hidden from configuration schemas; a saved
Tile's database ID is returned by its mutation and is used in the layout.

For the Workspace, use the catalog's advertised fields. Resolve the current
user through `get_current_user` if ownership must be supplied. A workspace's
`module_id` scopes it to a module; null denotes a general workspace. Discover
module identities rather than guessing them. Selection and sharing are model
settings: use them only when requested and writable. Selecting a workspace can
deselect another workspace belonging to that user in the same module scope.

## Configure tiles from the live schemas

Each `tile_types` entry supplies a `config_schema` for the Tile's `schema` value.
Read descriptions, required properties, defaults and nested `$defs`/`$ref`
definitions. Use renderable entries with a configuration schema. Do not invent
tile types, fields, options, IDs, routes or SQL columns.

For links, use `view_pages` to discover the intended page's instance-local URL.
Put that URL in the link's `url`, and provide a visible `name`. A route name is
not a substitute for a URL in a user-created tile. Folders contain ordered
`children`; the live schema describes nesting and icons.

For analytics, choose exactly one `oneOf` branch in the configuration schema.
The outer Tile.type identifies the analytics tile; `schema.type` identifies its
analytics subtype. Configure that branch's field slots and options. Each slot
contains a list of selected query columns, with each entry shaped as
`{"name": "query_column_alias", "opts": {...}}`. Field-specific options go in
that entry's `opts`; tile-level options go in `schema.opts`.

Discover accessible tables and fields using `api_sql_accessible_tables`, then
check a read-only query with `api_sql_execute`. Use the actual SQL dialect and
column aliases returned by those tools. Match selected field names exactly to
the query's output columns. Respect `x-field-types` and
`x-choices-by-field-type`: choices may depend on a column's primitive type even
when the schema enumerates the union of all available choices. The server may
impose further permissions and runtime checks.

For a total-count KPI, a query returning one `COUNT(*)` column can select that
alias with the `FIRST` aggregator. Applying `COUNT` again would count result
rows rather than display the total. Category charts sum their numeric columns
within each category. Follow the live branch and option descriptions for the
chosen subtype instead of assuming all analytics tiles aggregate alike.

### Analytics filters

`schema.filters` registers query-result columns for interactive filtering; it
does not store selected filter values. Use a list, for example:

```json
"filters": [{"field": "department", "type": "text"}]
```

The query must return `department` with that exact alias. A registered column
need not be selected in the display slots. Use its primitive result type:
`text`, `numeric`, `bool`, `date`, or `datetime`. Do not put filter registrations
in `fields.filter`, or add `operator`, `lookup`, or `value` to these entries.
The workspace filter UI supplies active conditions separately at request time.

Interactive conditions filter the query's output, after SQL aggregation. For
example, filtering `department` in a query grouped by department selects the
returned department groups. It cannot recalculate a single global `COUNT(*)`
by department if the query returns only `total`. Put permanent restrictions
and predicates that must run before aggregation in the SQL `WHERE` clause.

To connect differently named filter columns across tiles, give their
registrations the same `shared_key` and compatible types. Without an explicit
key, sharing uses `filter_shared_keys[field]`, falling back to the column name.
To keep a column tile-specific, set `filter_shared_keys` to
`{"department": null}` and leave that registration's `shared_key` unset.
Sharing requires at least two compatible participating tile fields; a key
alone does not create a filter on another tile.

For a model dataview, resolve the model label from permitted discovery and call
`get_content_type`. Put its returned integer ID in `content_type_id`. For a
Todo dataview, discover the installed Todo model label rather than assuming
the employee or Todo app labels are the same on every instance. Leave optional
view preferences unset unless a suitable accessible preference has been
discovered. Configuring a dataview does not bypass record or action permissions.

## Save tiles, then assemble the workspace

Create each Tile through mutations and retain its returned database ID. Then
create the Workspace with a `layout` that references those IDs. Consult
`layout_schema` for the complete layout structure. The usual minimal layout is:

```json
{
  "rows": [
    {
      "title": "Overview",
      "columns": 2,
      "items": [
        {"id": "RETURNED_TILE_ID_1", "colspan": 1},
        {"id": "RETURNED_TILE_ID_2", "colspan": 1}
      ]
    }
  ]
}
```

Replace placeholders with returned Tile IDs. Row and item order controls the
display order; `columns` controls the row grid and `colspan` controls an item's
width. Use positive widths that fit within the row. Item `config` is an
optional layout-level dictionary, not the Tile's configuration `schema`.
The layout contains references to saved tiles rather than nested Tile records.

When updating a workspace, retrieve its current layout first and preserve the
items the user wants to keep. A replacement `layout` must contain the entire
intended layout. If creation partially fails, keep successful record IDs and
resume from them; do not create duplicates or claim the workspace is finished.

Verify successful mutation results and retrieve saved records when permitted.
Report which tiles were saved and any remaining configuration or unavailable
capabilities. Saving configuration alone does not prove a SQL-backed tile has
rendered successfully. Open the saved workspace using a verified returned or
resolved URL and the available navigation tools; target a known browser tab
when possible. If navigation is unavailable, provide the verified link.
