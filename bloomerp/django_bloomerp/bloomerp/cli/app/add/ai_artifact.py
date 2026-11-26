# Proposed scaffolding parameters for a versioned AI artifact type.
# app: str | None = None - Target app; resolve with cli.app._utils.resolve_app_dir.
# name: str - Python module name and generated symbol prefix.
# key: str - Stable artifact type key used by AI_ARTIFACT_REGISTRY.
# label: str - Human-readable artifact label.
# schema_version: int = 1 - Positive version retained for persisted payloads.
# model: str | None = None - Payload model import path; generate one when omitted.
# describe: str | None = None - Description callback import path or generated stub.
# authorize: str | None = None - Optional source-authorization callback import path.
# icon: str | None = None - Icon shown alongside the artifact.
# render_cls: str | None = None - Optional artifact renderer class import path.
# search: bool = False - Scaffold an artifact search implementation.
# upload: bool = False - Scaffold an artifact upload implementation.
# selection_file_id: str | None = None - Optional selected-file resolver import path.
# tool_names: tuple[str, ...] = () - Related tools declared by the artifact type.
# tool_result_adapters: tuple[str, ...] = () - Tool-result adapter class import paths.
# Registration: AI_ARTIFACT_REGISTRY.register(key, definition).
