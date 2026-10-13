"""HTTP transport for router-registered MCP tools and resources."""

import base64
import logging
from typing import Any
from urllib.parse import urlsplit
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse

from bloomerp.api.base import AUTHENTICATION_CLASSES
from bloomerp.api.authentication_classes import BloomerpOAuthAuthentication
from bloomerp.oauth import MCP_SCOPE, oauth_enabled, oauth_metadata_url
from bloomerp.mcp.definition import McpResource, McpResourceTemplate, McpTool, validate_resource_uri
from bloomerp.router import BloomerpRoute, RouteType, ViewType, router
from jsonschema import Draft202012Validator
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.exceptions import PermissionDenied as ApiPermissionDenied
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class McpEndpointView(APIView):
    """Serve stateless MCP requests through authenticated router views."""

    authentication_classes = (BloomerpOAuthAuthentication,) + AUTHENTICATION_CLASSES
    permission_classes = (IsAuthenticated,)
    http_method_names = ("post", "options")

    def get_permissions(self) -> list[BasePermission]:
        """Allow OAuth clients to discover MCP catalogs before account linking."""
        if oauth_enabled():
            return [AllowAny()]
        return super().get_permissions()

    def get_authenticate_header(self, request: Request) -> str:
        """Direct OAuth-capable clients to the MCP resource metadata."""
        if oauth_enabled():
            return (
                f'Bearer resource_metadata="{oauth_metadata_url(request)}", '
                'error="invalid_token", error_description="MCP authentication required"'
            )
        return super().get_authenticate_header(request)

    def post(self, request: Request) -> Response:
        """Handle one JSON-RPC request or notification over Streamable HTTP."""
        origin = request.headers.get("Origin")
        if origin is not None:
            expected = urlsplit(request.build_absolute_uri())
            supplied = urlsplit(origin)
            if (supplied.scheme, supplied.netloc) != (expected.scheme, expected.netloc):
                return Response(status=403)

        if request.content_type != "application/json":
            return Response(status=415)
        if not {"application/json", "text/event-stream"}.issubset(
            {part.strip() for part in request.headers.get("Accept", "").split(",")}
        ):
            return Response(status=406)

        protocol_version = request.headers.get("MCP-Protocol-Version")
        supported_versions = {"2025-03-26", "2025-06-18", "2025-11-25"}
        if protocol_version is not None and protocol_version not in supported_versions:
            return Response(status=400)

        message = request.data
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return self._error(None, -32600, "Invalid Request")
        method = message.get("method")
        message_id = message.get("id")
        if not isinstance(method, str):
            return self._error(message_id, -32600, "Invalid Request")
        if "id" not in message:
            return Response(status=202)
        if not isinstance(message_id, (str, int)) or isinstance(message_id, bool):
            return self._error(None, -32600, "Invalid Request")
        params = message.get("params", {})
        if not isinstance(params, dict):
            return self._error(message_id, -32602, "Invalid params")

        if method == "initialize":
            requested = params.get("protocolVersion", "2025-11-25")
            negotiated = requested if requested in supported_versions else "2025-11-25"
            return self._result(message_id, {
                "protocolVersion": negotiated,
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": "Bloomerp", "version": "0.1.0"},
            })
        if method == "ping":
            return self._result(message_id, {})
        if method in {"resources/list", "resources/templates/list"}:
            if params.get("cursor") is not None:
                return self._error(message_id, -32602, "Resource catalogs do not accept cursors")
            templates = method == "resources/templates/list"
            routes = router.get_mcp_resource_templates() if templates else router.get_mcp_resources()
            key = "resourceTemplates" if templates else "resources"
            return self._result(message_id, {
                key: [self._resource_definition(route) for route in routes],
            })
        if method == "resources/read":
            if not request.user.is_authenticated:
                header = self.get_authenticate_header(request)
                return Response(
                    self._error(message_id, -32001, "MCP authentication required").data,
                    status=401, headers={"WWW-Authenticate": header} if header else None,
                )
            return self._read_resource(request, message_id, params)
        if method == "tools/list":
            try:
                return self._result(message_id, {
                    "tools": [self._tool_definition(route) for route in router.get_mcp_routes()]
                })
            except (TypeError, ValueError):
                logger.exception("Could not build MCP tool catalog")
                return self._error(message_id, -32603, "Internal error")
        if method == "tools/call":
            if not request.user.is_authenticated:
                return self._result(message_id, {
                    "content": [{"type": "text", "text": "Connect your Bloomerp account to use this tool."}],
                    "isError": True,
                    "_meta": {"mcp/www_authenticate": [
                        f'Bearer resource_metadata="{oauth_metadata_url(request)}", '
                        'error="invalid_token", error_description="Account linking required"'
                    ]},
                })
            return self._call_tool(request, message_id, params)
        return self._error(message_id, -32601, "Method not found")

    @staticmethod
    def _result(message_id: str | int, result: dict[str, Any]) -> Response:
        """Wrap a successful MCP result in a JSON-RPC response."""
        return Response({"jsonrpc": "2.0", "id": message_id, "result": result})

    @staticmethod
    def _error(message_id: str | int | None, code: int, message: str) -> Response:
        """Wrap a protocol failure in a JSON-RPC error response."""
        return Response({
            "jsonrpc": "2.0", "id": message_id,
            "error": {"code": code, "message": message},
        })

    @staticmethod
    def _tool_definition(route: BloomerpRoute) -> dict[str, Any]:
        """Advertise a registered route as an MCP tool."""
        contract = route.mcp
        assert isinstance(contract, McpTool)
        definition: dict[str, Any] = {
            "name": route.url_name,
            "description": contract.description or route.description or route.name,
            "inputSchema": contract.get_input_schema(),
        }
        if contract.title:
            definition["title"] = contract.title
        output_schema = contract.get_output_schema()
        if output_schema is not None:
            definition["outputSchema"] = output_schema
        annotations = contract.get_annotations()
        if annotations:
            definition["annotations"] = annotations
        if oauth_enabled():
            definition["securitySchemes"] = [{"type": "oauth2", "scopes": [MCP_SCOPE]}]
        return definition

    @staticmethod
    def _resource_definition(route: BloomerpRoute) -> dict[str, Any]:
        """Advertise resource identity and metadata without invoking its reader."""
        contract = route.mcp
        assert isinstance(contract, (McpResource, McpResourceTemplate))
        definition: dict[str, Any] = {
            "name": route.url_name, "title": contract.title or route.localized_name,
            "description": contract.description or route.localized_description,
            "mimeType": contract.mime_type,
        }
        if isinstance(contract, McpResource):
            definition["uri"] = contract.uri
        else:
            definition["uriTemplate"] = contract.uri_template
        return definition

    def _read_resource(
        self, request: Request, message_id: str | int, params: dict[str, Any],
    ) -> Response:
        """Resolve a registered URI and run its reader as the authenticated caller."""
        uri = params.get("uri")
        if not isinstance(uri, str):
            return self._error(message_id, -32602, "Resource URI must be a string")
        try:
            validate_resource_uri(uri)
            resolved = router.resolve_mcp_resource(uri)
        except ValueError as error:
            return self._error(message_id, -32602, str(error))
        if resolved is None:
            return self._error(message_id, -32002, "Resource not found")
        route, arguments = resolved
        contract = route.mcp
        assert isinstance(contract, (McpResource, McpResourceTemplate))
        try:
            if isinstance(contract, McpResourceTemplate):
                schema = contract.get_parameter_schema()
                Draft202012Validator.check_schema(schema)
                errors = list(Draft202012Validator(schema).iter_errors(arguments))
                if errors:
                    return self._error(message_id, -32602, errors[0].message)
            result = self._dispatch_view(request, route, arguments)
            status_code = getattr(result, "status_code", 200)
            if status_code in {401, 403}:
                return self._error(message_id, -32001, "Resource access denied")
            if status_code == 404:
                return self._error(message_id, -32002, "Resource not found")
            if status_code >= 400:
                return self._error(message_id, -32603, "Resource reader failed")
            payload = result.data if isinstance(result, Response) else result
            if isinstance(payload, HttpResponse):
                payload = payload.content
                if contract.mime_type.startswith("text/") or contract.mime_type == "application/json":
                    payload = payload.decode(result.charset)
            content: dict[str, Any] = {"uri": uri, "mimeType": contract.mime_type}
            if isinstance(payload, bytes):
                content["blob"] = base64.b64encode(payload).decode("ascii")
            elif isinstance(payload, str):
                content["text"] = payload
            elif isinstance(payload, (dict, list)):
                content["text"] = JSONRenderer().render(payload).decode("utf-8")
            else:
                raise TypeError("Resource readers must return text, bytes, or JSON objects/arrays")
            return self._result(message_id, {"contents": [content]})
        except (PermissionDenied, ApiPermissionDenied):
            return self._error(message_id, -32001, "Resource access denied")
        except Http404:
            return self._error(message_id, -32002, "Resource not found")
        except Exception:
            logger.exception("MCP resource %s failed", uri)
            return self._error(message_id, -32603, "Resource reader failed")

    def _call_tool(
        self, request: Request, message_id: str | int, params: dict[str, Any]
    ) -> Response:
        """Validate tool arguments and dispatch through the registered view."""
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return self._error(message_id, -32602, "Invalid params")
        route = next(
            (item for item in router.get_mcp_routes() if item.url_name == name), None
        )
        if route is None:
            return self._error(message_id, -32602, "Unknown tool")
        assert isinstance(route.mcp, McpTool)
        try:
            errors = list(Draft202012Validator(route.mcp.get_input_schema()).iter_errors(arguments))
        except (TypeError, ValueError):
            logger.exception("Invalid MCP input schema for %s", name)
            return self._error(message_id, -32603, "Internal error")
        if errors:
            return self._result(message_id, {
                "content": [{"type": "text", "text": errors[0].message}],
                "isError": True,
            })

        try:
            result = self._dispatch_view(request, route, arguments)
            payload = result.data if isinstance(result, Response) else result
            status_code = getattr(result, "status_code", 200)
            serialized = JSONRenderer().render(payload).decode("utf-8")
            tool_result: dict[str, Any] = {
                "content": [{"type": "text", "text": serialized}],
            }
            if status_code >= 400:
                tool_result["isError"] = True
            elif isinstance(payload, dict):
                tool_result["structuredContent"] = payload
            return self._result(message_id, tool_result)
        except Exception:
            logger.exception("MCP tool %s failed", name)
            return self._result(message_id, {
                "content": [{"type": "text", "text": "Tool execution failed"}],
                "isError": True,
            })

    @staticmethod
    def _dispatch_view(
        request: Request, route: BloomerpRoute, arguments: dict[str, Any]
    ) -> Any:
        """Re-enter a route's view with the authenticated caller's identity."""
        if route.route_type == RouteType.MCP_RESOURCE:
            method = "get"
        elif route.route_type == RouteType.MCP or route.view_type == ViewType.FUNCTION:
            method = "post"
        else:
            methods = [
                name for name in ("get", "post")
                if hasattr(route.view, name)
                and name in getattr(route.view, "http_method_names", ())
            ]
            if len(methods) != 1:
                raise ValueError("MCP API views must expose exactly one GET or POST method")
            method = methods[0]
        factory = APIRequestFactory()
        path = route.path or "/mcp"
        forwarded_context = {"HTTP_HOST": request.get_host(), "secure": request.is_secure()}
        if method == "get":
            forwarded = factory.get(path, data=arguments, **forwarded_context)
        else:
            forwarded = factory.post(path, data=arguments, format="json", **forwarded_context)
        force_authenticate(forwarded, user=request.user, token=request.auth)
        forwarded.user = request.user
        forwarded.auth = request.auth
        forwarded.data = arguments
        if route.view_type == ViewType.CLASS:
            view_callable = route.view.as_view(**router._get_route_kwargs(route))
            view_arguments = arguments if route.route_type == RouteType.MCP_RESOURCE else {}
            return view_callable(forwarded, **view_arguments)
        view_kwargs = router._get_route_kwargs(route)
        if route.route_type == RouteType.MCP_RESOURCE:
            view_kwargs.update(arguments)
        return route.view(forwarded, **view_kwargs)
