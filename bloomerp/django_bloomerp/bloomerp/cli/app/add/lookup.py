# Proposed scaffolding parameters for a field-independent filter lookup.
# app: str | None = None - Target app; resolve with cli.app._utils.resolve_app_dir.
# name: str - Python module name and generated symbol prefix.
# id: str - Stable LookupDefinition.id and LOOKUP_REGISTRY registration key.
# label: str - Human-readable operator label.
# expressions: tuple[str, ...] = () - Supported expressions; required unless nested.
# description: str | None = None - Explanation of the operator.
# nested: bool = False - Whether execution delegates to a nested terminal lookup.
# q_factory: str | None = None - Optional Django ORM compiler import path.
# sql_factory: str | None = None - Optional parameterized SQL compiler import path.
# python_evaluator: str | None = None - Optional in-memory evaluator import path.
# default_form_factory: str | None = None - Optional filter value editor factory path.
# nested_fields_factory: str | None = None - Optional nested-field resolver path.
# Registration: LOOKUP_REGISTRY.register(id, definition); field.py binds lookups.
