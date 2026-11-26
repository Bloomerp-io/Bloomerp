# Proposed scaffolding parameters for a voice/SMS telephony provider.
# app: str | None = None - Target app; resolve with cli.app._utils.resolve_app_dir.
# name: str - Python module name and generated symbol prefix.
# key: str - VoIP provider key used by VOIP_PROVIDER_REGISTRY.
# display_name: str - Provider name shown in the connection picker.
# description: str = "" - Provider guidance.
# icon: str = "" - Provider icon.
# adapter_class: str | None = None - BaseVoIPAdapter subclass import path or scaffold.
# config_schema: str | None = None - Connection configuration model path or scaffold.
# number_search_schema: str | None = None - Optional number-search model import path.
# number_purchase_schema: str | None = None - Optional number-purchase model path.
# purchase_notice: str = "" - Guidance displayed before purchasing a number.
# pricing_url: str = "" - Provider pricing link.
# account_id_field: str = "" - Provider account identity field.
# immutable_config_fields: tuple[str, ...] = () - Connection fields locked after setup.
# webhook_handlers: dict[str, str] | None = None - Callback names and handler paths.
# callback_labels: dict[str, str] | None = None - Human-readable callback labels.
# callback_help: str = "" - Instructions for configuring callbacks.
# configuration_help: str = "" - Connection setup instructions.
# browser_driver: str = "" - Existing shipped browser driver, if supported.
# operation_errors: tuple[str, ...] = () - Exception class import paths to handle.
# max_sms_length: int = 1600 - Provider message length limit.
# max_assigned_users: int | None = None - Optional shared-number assignment limit.
# Registration: VOIP_PROVIDER_REGISTRY.register(key, definition).
