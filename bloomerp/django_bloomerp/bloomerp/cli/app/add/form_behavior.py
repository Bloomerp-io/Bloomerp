# Proposed scaffolding parameters for a form behavior action.
# app: str | None = None - Target app; resolve with cli.app._utils.resolve_app_dir.
# name: str - Python module name and generated symbol prefix.
# id: str - Stable BehaviorActionDefinition.id and ACTION_REGISTRY key.
# label: str - Human-readable action label.
# description: str - Guidance explaining the action's effect.
# group: str | None = None - Optional behavior-builder action group.
# requires_target_field: bool = True - Whether the action requires a target field.
# execute: str | None = None - Execution callback import path or generated typed stub.
# config_form_factory: str | None = None - Optional configuration-form factory path.
# get_listener_fields: str | None = None - Optional listener-field selector path.
# get_target_fields: str | None = None - Optional target-field selector path.
# Registration: ACTION_REGISTRY.register(id, definition) via an explicit app import.
