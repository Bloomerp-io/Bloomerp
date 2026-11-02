# Workspaces and tiles

A workspace is a selectable layout of tiles. `Workspace` stores a user's
preference for a module (or the general workspace); `Tile` stores a reusable
tile configuration. Sharing a layout does not grant access to its underlying
data.

## Declare a module workspace

Add tile configurations and layouts to a `BloomerpModule`. For example, in an
installed app's `modules.py`:

```python
from bloomerp.models.definition import LayoutItem, LayoutRow, WorkspaceLayout
from bloomerp.modules.definition import BloomerpModule
from bloomerp.workspaces.text_tile.model import TextTileConfig


class SalesModule(BloomerpModule):
    """Provide a sales workspace with a reusable welcome tile."""

    id = "sales"
    name = "Sales"
    tiles = [
        TextTileConfig(
            id="sales-welcome",
            name="Welcome",
            markdown="## Sales\nChoose a model to start working.",
        ),
    ]
    workspaces = [
        WorkspaceLayout(
            name="Overview",
            is_default=True,
            rows=[
                LayoutRow(
                    columns=1,
                    items=[LayoutItem(id="sales-welcome")],
                ),
            ],
        ),
    ]
```

Tile IDs must be nonempty, stable, and unique. Layout items reference those
IDs; an unknown tile ID fails when the workspace is created. A module with
configured workspaces must have unique workspace names and exactly one default.
Models can contribute reusable tiles through `BloomerpModelConfig.tiles`.

The default workspace lifecycle materializes configured tiles and replaces
layout IDs with persisted tile IDs when creating user preferences. Treat these
as defaults for preference creation, not as a way to overwrite users' saved
layouts on every request.

## Filters

Use the [shared filter editor](../fields/filter-editor.md) with workspace scope.
A tile-specific field path looks like `tile_<id>:customer__name`; compatible
fields across multiple tiles can share a `shared:<key>` path.

`filter_shared_keys` maps field names to a shared key. Set a value to `None` to
keep that field tile-specific. Analytics and dataview renderers project shared
conditions to each participating tile before executing them. A tile that does
not participate in a condition is not filtered by it. Explicit empty AND/OR
groups retain their true/false semantics.

Do not execute a shared condition using only the representative field returned
by editor discovery. Use `FilterFieldResolver.resolve_all()` or
`resolve_for_tile()` as described in the
[workspace filter contract](../fields/filter-editor.md#shared-workspace-fields).
