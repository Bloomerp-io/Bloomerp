# Proposed scaffolding parameters for an AI provider and its runtime factory.
# app: str | None = None - Target app; resolve with cli.app._utils.resolve_app_dir.
# name: str - Python module name and generated symbol prefix.
# id: str - Stable provider ID used by AI_PROVIDER_REGISTRY.
# label: str - Human-readable AIProviderDefinition.name.
# description: str = "" - Provider guidance shown in the picker.
# runtime: str = "pydantic_ai" - Runtime identifier advertised by the provider.
# runtime_factory: str | None = None - Factory import path or generated typed stub.
# credentials_schema: str | None = None - Credentials model import path or scaffold.
# config_schema: str | None = None - Provider configuration model import path or scaffold.
# integration: str | None = None - Optional integration object import path.
# model_identifier_factory: str | None = None - Optional model-discovery callback path.
# Registration: AI_PROVIDER_REGISTRY.register(key, definition), using the provider ID.
