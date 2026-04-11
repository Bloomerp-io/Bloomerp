# Workspace Tiles

This folder contains the tile system used by workspaces.

At the top level there are three main concepts:

- `TileType` in `tiles.py`: the registry of all workspace tile families.
- `BaseTileConfig` and `BaseTileRenderer` in `base.py`: the common contract every tile follows.
- the create/preview flow: the wizard stores tile state in the session, and the preview component renders the current config live.

## Core pieces

### `base.py`

This file defines the shared abstractions.

- `BaseTileConfig`
	- Pydantic model that stores the state needed to render a tile.
	- Must implement `get_default()`.
	- Must implement `get_operation()` if the tile supports live builder actions.
- `BaseTileRenderer`
	- Responsible for turning a tile config into HTML.
	- Usually delegates to a Django template via `render_to_string()`.
- `TileOperationDefinition`
	- Connects one builder action to a validation model and a handler.
- `TileOperationHandler`
	- Applies one small config update.
- `TileOperationHandlerRespone`
	- Returns the updated config plus an optional UI message.

The design is intentionally simple: tile configuration is plain data, rendering is isolated, and interactive changes are small explicit operations.

### `tiles.py`

This is the main registry.

Each enum value is a `TileTypeDefinition` with:

- a display name
- a description
- an icon
- a config model
- a renderer class
- optionally a form class

This is the entry point that makes a tile family visible to the rest of the workspace UI.

## How the tile flow works

### 1. Tile type selection

The create-tile wizard in `views/workspace/create_tile.py` starts by letting the user choose a `TileType`.

That choice is stored in the wizard session.

### 2. Tile-specific setup

Each tile family can have a different flow.

- analytics tiles first collect a SQL query
- other tile families can go directly to a builder or config step

The current wizard infrastructure is session-backed through `BaseStateOrchestrator` and `TileBuilderOrchestrator`.

### 3. Live preview

`components/workspaces/preview_workspace_tile.py` is the central preview endpoint.

It:

- reads the current tile type from the session
- reconstructs the tile config from session data
- renders the preview through the tile renderer
- handles builder operations such as add/remove/toggle/update actions
- persists the updated config back into session state

This means tile builders do not mutate models directly. They only post operations, receive a new config, and re-render.

### 4. Renderers

Each tile family has one top-level renderer class registered in `tiles.py`.

Examples:

- `LinksTileRenderer`
- `CanvasTileRenderer`
- `AnalyticsTileRenderer`

That renderer can either render directly or dispatch to a more specialized renderer. Analytics tiles do the second.

## Existing tile families

### `links_tile`

Simple example of a non-query tile.

- config stores links
- operations add, remove, and update links
- renderer outputs the final link list

This is the cleanest example if you want to understand the base tile pattern.

### `analytics_tile`

Query-driven tile family.

- config stores the SQL query and analytics-specific builder state
- top-level renderer fetches the data
- a second registry decides how the selected analytics subtype renders that data

See `analytics_tile/readme.md` for details.

### `dataview_tile`

Model-backed tile family.

- config stores content type, view type, and selected fields
- operations update those choices incrementally

## How to add a new tile family

If you want to add a new top-level workspace tile type, the normal path is:

1. Create a new folder under `workspaces/`.
2. Add a config model that extends `BaseTileConfig`.
3. Add a renderer that extends `BaseTileRenderer`.
4. If the tile is interactive, add operation models and handlers through `get_operation()`.
5. Register the tile family in `tiles.py`.
6. Add or reuse a builder template in `components/workspaces/tile_builders/`.
7. Update `PreviewWorkspaceTile.get_tile_builder_template()` if the tile needs a custom builder.
8. Update the create-tile wizard if the tile needs extra setup steps before the builder.

## How to think about operations

Builder operations should stay small and local.

Good operations:

- set one type
- toggle one field
- add one link
- remove one selected field
- update one option group

Avoid handlers that try to rebuild the whole config from scratch. The existing codebase prefers incremental updates that are easy to validate and easy to preview.

## Recommended implementation style

- Keep config as plain Pydantic data.
- Keep rendering separate from state mutation.
- Prefer one small operation per UI action.
- Use declarative definitions when a tile has repeated configuration structure.
- Let the preview endpoint own session persistence.
- Keep templates simple and let the Python side prepare the data shape they need.

## Minimal example checklist

For a new tile family, the smallest viable implementation is:

1. A `BaseTileConfig` subclass with `get_default()` and `get_operation()`.
2. A renderer class with a template.
3. A `TileType` registration.
4. A preview builder template or the default builder.

After that, you can add richer builder interactions incrementally.
