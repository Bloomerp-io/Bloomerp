# Proposed scaffolding parameters for a reusable workspace tile type.
# app: str | None = None - Target app; resolve with cli.app._utils.resolve_app_dir.
# name: str - Python module name and generated symbol prefix.
# key: str - Symbolic TILE_TYPE_REGISTRY key.
# label: str - Human-readable TileTypeDefinition.name.
# description: str - Explanation of the tile's purpose.
# icon: str = "" - Tile picker icon.
# model: str | None = None - BaseTileConfig subclass import path or scaffold.
# render_cls: str | None = None - BaseTileRenderer subclass import path or scaffold.
# form_cls: str | None = None - Optional configuration form import path.
# template_name: str | None = None - Template to use or create for tile rendering.
# filter_fields_factory: str | None = None - Optional tile filter factory import path.
# operations: tuple[str, ...] = () - Config operations and handlers to scaffold.
# Registration: TILE_TYPE_REGISTRY.register(key, definition).
