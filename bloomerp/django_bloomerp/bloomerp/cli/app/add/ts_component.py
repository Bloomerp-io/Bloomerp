# Proposed scaffolding parameters for an app-owned TypeScript frontend component.
# app: str | None = None - Target app; resolve with cli.app._utils.resolve_app_dir.
# name: str - TypeScript file name and generated component class prefix.
# component_id: str - Namespaced registerComponent ID, for example production:planner.
# override: bool = False - Explicitly replace an existing component registration.
# template_name: str | None = None - Optional template containing component markup.
# styles: bool = False - Scaffold a component stylesheet and import it.
# hooks: tuple[str, ...] = () - Lifecycle hooks to scaffold: initialize,
#   onAfterSwap, and destroy; initialization belongs outside the constructor.
# Registration: registerComponent(component_id, Component, { override }) through
#   @bloomerp/frontend, imported by the app frontend entry point.
