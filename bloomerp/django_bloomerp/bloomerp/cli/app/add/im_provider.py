# Proposed scaffolding parameters for an instant messaging provider.
# app: str | None = None - Target app; resolve with cli.app._utils.resolve_app_dir.
# name: str - Python module name and generated symbol prefix.
# key: str - IM provider key used by IM_PROVIDER_REGISTRY.
# display_name: str - Provider name shown in the messaging interface.
# icon: str - Messaging provider icon.
# description: str = "" - Provider guidance.
# address_field: str - Recipient address field used by this provider.
# adapter_class: str | None = None - BaseIMAdapter subclass import path or scaffold.
# config_schema: str | None = None - Connection configuration model path or scaffold.
# auth_mode: str = "internal" - internal, embedded_signup, or oauth.
# internal: bool = False - Whether the provider represents internal messaging.
# transport_ready: bool = False - Whether a usable transport is implemented.
# capabilities: tuple[str, ...] = () - Planned IMCapabilities flags to configure.
# hooks: tuple[str, ...] = () - Scaffold start_handler, send_handler,
#   actions_resolver, and identity_label_resolver.
# selection_steps: tuple[str, ...] = () - Recipient-selection definition import paths.
# creation_actions: tuple[str, ...] = () - Conversation-creation action import paths.
# timeline_sources: tuple[str, ...] = () - Conversation timeline source import paths.
# calling: str | None = None - Optional IMCallingDefinition import path.
# Registration: IM_PROVIDER_REGISTRY.register(key, definition).
