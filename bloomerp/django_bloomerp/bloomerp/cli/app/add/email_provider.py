# Proposed scaffolding parameters for an email transport provider.
# app: str | None = None - Target app; resolve with cli.app._utils.resolve_app_dir.
# name: str - Python module name and generated symbol prefix.
# key: str - Email provider key used by EMAIL_PROVIDER_REGISTRY.
# label: str - Human-readable EmailProviderDefinition.name.
# description: str = "" - Provider description.
# icon: str = "" - Account picker icon.
# adapter_class: str | None = None - BaseEmailAdapter subclass import path or scaffold.
# fields: tuple[str, ...] = () - Existing EmailAccount fields shown during setup.
# required_fields: tuple[str, ...] = () - Required setup fields.
# initial: dict[str, object] | None = None - Non-secret setup defaults.
# setup_instructions: str | None = None - Provider setup guidance.
# sync_modes: tuple[str, ...] = ("polling",) - Supported polling/push strategies.
# default_sync_mode: str = "polling" - Default supported synchronization strategy.
# poll_interval_minutes: int = 5 - Default interval for polling.
# authorization: bool = False - Scaffold start/complete authorization callbacks.
# mailbox_defaults: str | None = None - Optional mailbox-defaults callback path.
# advanced_rendering: str | None = None - Optional provider email rendering template.
# Registration: EMAIL_PROVIDER_REGISTRY.register(key, definition).
