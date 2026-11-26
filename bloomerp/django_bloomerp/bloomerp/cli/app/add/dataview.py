# Proposed scaffolding parameters for a collection dataview type.
# app: str | None = None - Target app; resolve with cli.app._utils.resolve_app_dir.
# name: str - Python module name and generated symbol prefix.
# key: str - Registry key; also the config model's default view_type.
# label: str - Human-readable dataview label.
# description: str = "" - Explanation of the collection presentation.
# icon: str = "" - Icon used in the dataview picker.
# renderer_cls: str | None = None - BaseDataviewRenderer subclass path or scaffold.
# config_cls: str | None = None - BaseDataview subclass path or scaffold.
# template_name: str | None = None - Template to use or create for the renderer.
# item_template_name: str - Shared per-record template for the renderer.
# record_based: bool = True - Aggregate views can declare False.
# requires_display_fields: bool = True - Whether the view needs selected fields.
# available_for_model: str | None = None - Optional model-availability callback path.
# operations: tuple[str, ...] = () - Named renderer operations to scaffold.
# Registration: register_dataview(definition) in the app's discovered dataviews module.
