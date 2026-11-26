# Proposed scaffolding parameters for a registry-backed field type.
# app: str | None = None - Target app; resolve with cli.app._utils.resolve_app_dir.
# name: str - Python module name and generated symbol prefix.
# key: str - Symbolic FIELD_TYPE_REGISTRY registration key.
# id: str - Persisted FieldTypeDefinition.id, distinct from the symbolic key.
# label: str - Human-readable field type label.
# description: str | None = None - Explanation shown during field discovery.
# icon: str = "fa-solid fa-table-columns" - Field type icon.
# model_field_cls: str | None = None - Django model field class import path.
# construction: bool = False - Scaffold model-builder options and defaults.
# lookups: tuple[str, ...] = () - Existing lookup keys to bind to this definition.
# hooks: tuple[str, ...] = () - Typed callbacks to scaffold: form_factory,
#   widget_factory, render_value, batch_value_loader, and display_options.
# Registration: FIELD_TYPE_REGISTRY.register(key, definition).
