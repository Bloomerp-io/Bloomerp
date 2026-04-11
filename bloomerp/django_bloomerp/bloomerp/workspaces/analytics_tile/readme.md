# Analytics Tiles

Analytics tiles are a tile family inside `workspaces/`, but they have their own internal subtype system.

The top-level workspace registry sees analytics as one tile type. Inside that tile type, analytics chooses a second renderer such as KPI or table based on the analytics config.

## Mental model

There are two levels:

### Workspace tile level

- registered in `workspaces/tiles.py` as `ANALYTICS_TILE`
- uses `AnalyticsTileConfig`
- uses `AnalyticsTileRenderer`

### Analytics subtype level

- registered in `analytics_tile/model.py` through `AnalyticsTileType`
- examples: `KPI`, `TABLE`, `TWO_DIM_CHART`
- each subtype defines its own field slots, options, and renderer

This split keeps the workspace system generic while letting analytics tiles evolve independently.

## Important files

### `model.py`

This is the main analytics definition file.

It contains:

- `AnalyticsTileConfig`
  - the persisted analytics builder state
  - includes the SQL query, selected subtype, selected fields, and global options
- `AnalyticsTileType`
  - the subtype registry
- `AnalyticsTileTypeDefinition`
  - the metadata for one analytics subtype
- `FieldDefinition`
  - one configurable field slot such as `value`, `sub_value`, or `columns`
- `OptionDefinition`
  - one configurable option such as label, formatter, prefix, or suffix
- operation handlers
  - `set_type`
  - `set_opts`
  - `set_field_opts`
  - `add_field`
  - `remove_field`

This file is the best place to start when adding or changing analytics behavior.

### `render.py`

`AnalyticsTileRenderer` is the analytics entry point.

It:

- resolves the selected `AnalyticsTileType`
- executes the SQL query through `SqlExecutor`
- converts the result to a dataframe
- delegates rendering to the subtype renderer

This means individual analytics renderers do not have to fetch their own data.

### `utils.py`

This file contains shared analytics helpers.

Examples:

- primitive field types
- field icons
- formatter definitions
- aggregator definitions
- dynamic choice helpers for builder forms

If a field option depends on the kind of data it is attached to, that logic usually belongs here.

### subtype renderer files

Each implemented subtype usually gets its own module.

Examples:

- `kpi.py`
- `table.py`

Those renderers receive three things:

- the analytics config
- the current user
- the dataframe already produced from the query

Their job is to transform that dataframe into the exact template payload needed by the UI.

## Builder flow

Analytics tiles have a two-step builder flow.

### 1. Query step

In `views/workspace/create_tile.py`, the user provides a SQL query.

That step:

- validates the query exists
- builds a default `AnalyticsTileConfig`
- executes the query once
- stores `output_table` metadata in the wizard session
- stores the query and config in the wizard session

The `output_table` metadata is what powers the field picker in the builder.

### 2. Builder step

In `components/workspaces/preview_workspace_tile.py`, the analytics builder:

- loads the current analytics subtype definition
- builds the global options form
- builds field-specific option forms
- filters available output fields by allowed primitive type
- recomputes output field icons from primitive types
- renders the live tile preview

All builder interactions post back as small operations that update the session config.

## Config shape

`AnalyticsTileConfig` currently stores:

- `query`: the SQL query
- `type`: the selected analytics subtype key
- `fields`: selected fields keyed by field slot name
- `opts`: global options for the subtype

`fields` has this general shape:

```python
{
    "columns": [
        {"name": "revenue", "opts": {"label": "Revenue", "formatter": "DOUBLE_US"}},
        {"name": "country", "opts": {"label": "Country"}},
    ],
    "value": [
        {"name": "count", "opts": {"aggregator": "COUNT"}},
    ],
}
```

Each selected field is a `FieldConfig` with a `name` and optional `opts`.

## How a subtype is defined

Each analytics subtype is defined declaratively in `AnalyticsTileType`.

The important parts are:

- `key`
- `name`
- `description`
- `icon`
- `render_cls`
- `fields`
- `opts`

### `fields`

Each `FieldDefinition` describes one slot in the builder.

Examples:

- KPI has `value` and `sub_value`
- table has `columns`

Each field definition can:

- allow one or many selected output fields
- expose field-level options
- restrict compatible output field types

### `opts`

These are subtype-wide options, not tied to a single selected field.

Example:

- table size

## How forms are generated

Forms are not handwritten per subtype.

Instead, `OptionDefinition` drives form generation.

`options_form_factory()` and `get_field_options_form_factory()` build Django forms from the declarative option definitions.

If an option exposes a `choices_provider`, those choices are resolved dynamically from the primitive type of the selected output field.

This is how formatter and aggregator choices stay compatible with the chosen field type.

## How to add a new analytics subtype

The normal path is:

1. Create a renderer module in `analytics_tile/`.
2. Add a subtype definition to `AnalyticsTileType` in `model.py`.
3. Point `render_cls` at the new renderer.
4. Define the field slots in `fields`.
5. Define any global options in `opts`.
6. Reuse existing `OptionDefinition`s where possible.
7. Add new helpers to `utils.py` only if the subtype needs shared logic.
8. Add a template under `templates/cotton/workspaces/tiles/`.

If the subtype fits the current builder model, that is enough for it to appear in the analytics builder automatically.

## Example: adding a simple subtype

For a small subtype, prefer this structure:

1. Declare one or two field slots.
2. Reuse `LABEL_OPTION`, `FORMATTER_OPTION`, `PREFIX_OPTION`, and `SUFFIX_OPTION` when they make sense.
3. Keep the renderer focused on turning a dataframe into template context.
4. Let the builder remain declarative instead of adding custom branching unless necessary.

This is the same pattern used by KPI and table.

## Practical guidance

- Put shared analytics concepts in `utils.py`.
- Put subtype structure in `model.py`.
- Put rendering logic in the subtype module.
- Keep templates dumb: prepare a clean payload in Python first.
- Prefer field-level options over ad hoc renderer conditionals.
- Only add custom builder behavior when the declarative field/option system is not enough.

## Current implemented examples

- KPI
  - supports value and sub-value fields
  - supports aggregators, formatters, prefix, and suffix
- Table
  - supports selected columns
  - supports label override, formatter, prefix, and suffix

These two are the best current references when implementing more analytics tile types.