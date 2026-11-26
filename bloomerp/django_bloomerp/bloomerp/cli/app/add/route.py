# Proposed scaffolding parameters for every router extension: pages, components,
# APIs, WebSockets, MCP tools, and concrete or parameterized MCP resources.
# app: str | None = None - Target app; resolve with cli.app._utils.resolve_app_dir.
# name: str - Python module name and generated view or consumer symbol prefix.
# route_type: str = "app" - app, module, model, detail, api, api_model, api_detail,
#   websocket, mcp, or mcp_resource; all stay within this single scaffolder.
# path: str | None = None - Django path; MCP-only registrations must omit it.
# re_path: str | None = None - Regex alternative to path, where supported.
# url_name: str | None = None - Stable URL name; also the MCP tool identity.
# label: str | None = None - Human-readable router name.
# description: str | None = None - Route description.
# models: tuple[str, ...] = () - Model import paths, or the __all__ selector.
# modules: tuple[str, ...] = () - Module IDs/import paths, or __all__.
# exclude_models: tuple[str, ...] = () - Model exclusions for model/detail routes.
# view_type: Literal["class", "function"] = "class" - HTTP handler scaffold style.
# view_class: str | None = None - Base view/Channels consumer import path or scaffold.
# template_name: str | None = None - Optional page or HTML fragment template.
# methods: tuple[str, ...] = ("GET",) - HTTP methods for HTTP view scaffolds only.
# override: bool = False - Explicitly replace a conflicting route registration.
# translatable: bool | None = None - Override route metadata translation behavior.
# searchable: bool | None = None - Override route search visibility.
# message_format_values: dict[str, str] | None = None - Route label placeholders.
# sdk: tuple[str, ...] = () - SdkEndpoint import paths, one per exposed HTTP method.
# mcp: str | None = None - McpTool/McpResource/McpResourceTemplate import path.
# mcp_title: str | None = None - Display title for a generated MCP contract.
# mcp_description: str | None = None - Guidance for a generated MCP contract.
# input_schema: str | None = None - MCP tool schema/factory import path.
# output_schema: str | None = None - Optional MCP tool output schema/factory path.
# memory: str | None = None - Optional McpMemoryPolicy import path for a tool.
# read_only_hint, destructive_hint, idempotent_hint, open_world_hint:
#   bool | None = None - Optional MCP tool behavior hints.
# uri: str | None = None - Absolute URI for a concrete MCP resource.
# uri_template: str | None = None - Resource URI template; mutually exclusive with uri.
# parameter_schema: str | None = None - Resource-template schema/factory import path.
# mime_type: str = "text/plain" - Content type for a generated MCP resource contract.
# Registration: @router.register(...); choose only parameters valid for route_type.
