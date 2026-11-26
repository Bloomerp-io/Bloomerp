# Proposed scaffolding parameters for a Bloomerp application module.
# app: str | None = None - Target app; resolve with cli.app._utils.resolve_app_dir.
# name: str - Python module name and generated BloomerpModule subclass prefix.
# id: str - Stable module identifier.
# label: str - Human-readable BloomerpModule.name.
# code: str | None = None - Module code; default to the uppercase ID.
# description: str | None = None - Optional module description.
# icon: str = "fa-solid fa-folder" - Navigation icon.
# parent_module_id: str | None = None - Parent module for nested navigation.
# route_path: str | None = None - Optional URL segment override.
# visible: bool = True - Whether the module appears in navigation.
# enabled: bool = True - Whether the module is enabled.
# tiles: tuple[str, ...] = () - Reusable tile configuration import paths.
# workspaces: tuple[str, ...] = () - WorkspaceLayout import paths.
# Registration: module_registry discovers BloomerpModule subclasses in app modules.
