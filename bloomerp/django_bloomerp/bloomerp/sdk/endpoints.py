"""Render opted-in router operations through each SDK's shared HTTP client."""

from __future__ import annotations

import json
import keyword
import re
from typing import TYPE_CHECKING

from django.db import models
from rest_framework import serializers

from bloomerp.sdk.definition import SdkEndpoint
from bloomerp.utils.models import model_name_plural_underline

if TYPE_CHECKING:
    from bloomerp.router import BloomerpRoute


class EndpointRenderer:
    """Derive nested request/response types and custom methods from DRF fields."""

    def __init__(self, language: str) -> None:
        """Select the output syntax and collect named nested serializer types."""
        self.language = language
        self.types: dict[str, str] = {}

    def field_type(self, field: serializers.Field, name: str, *, output: bool) -> str:
        """Map a serializer field, respecting direction, nesting, choices, and nulls."""
        python = self.language == "python"
        unknown = "Any" if python else "unknown"
        if isinstance(field, (serializers.ListSerializer, serializers.ListField, serializers.ManyRelatedField)):
            child = field.child_relation if isinstance(field, serializers.ManyRelatedField) else field.child
            child_type = self.field_type(child, name + "Item", output=output)
            result = f"list[{child_type}]" if python else f"Array<{child_type}>"
        elif isinstance(field, serializers.BaseSerializer):
            members: list[str] = []
            for key, child in field.fields.items():
                if isinstance(child, serializers.HiddenField) or (child.write_only if output else child.read_only):
                    continue
                child_name = name + "".join(part.capitalize() for part in key.split("_"))
                child_type = self.field_type(child, child_name, output=output)
                required = child.required or (output and child.read_only)
                if python:
                    value = child_type if required else f"NotRequired[{child_type}]"
                    members.append(f"    {key!r}: {value},")
                else:
                    members.append(f"  {json.dumps(key)}{'' if required else '?'}: {child_type};")
            if python:
                self.types[name] = f'{name} = TypedDict("{name}", {{\n' + "\n".join(members) + "\n})"
            else:
                self.types[name] = f"export interface {name} {{\n" + "\n".join(members) + "\n}"
            result = name
        elif isinstance(field, serializers.MultipleChoiceField):
            values = self.choice_type(list(field.choices))
            result = f"list[{values}]" if python else f"Array<{values}>"
        elif isinstance(field, serializers.ChoiceField):
            result = self.choice_type(list(field.choices))
        elif isinstance(field, serializers.DictField):
            child_type = self.field_type(field.child, name + "Value", output=output)
            result = f"dict[str, {child_type}]" if python else f"Record<string, {child_type}>"
        elif isinstance(field, serializers.PrimaryKeyRelatedField):
            if field.pk_field is not None:
                result = self.field_type(field.pk_field, name, output=output)
            else:
                related_model = getattr(field.get_queryset(), "model", None)
                numeric = related_model is not None and isinstance(related_model._meta.pk, models.IntegerField)
                if related_model is None:
                    result = "str | int" if python else "string | number"
                else:
                    result = ("int" if python else "number") if numeric else ("str" if python else "string")
        elif isinstance(field, serializers.BooleanField):
            result = "bool" if python else "boolean"
        elif isinstance(field, serializers.IntegerField):
            result = "int" if python else "number"
        elif isinstance(field, serializers.DecimalField):
            # DRF decimal responses are strings unless explicitly configured otherwise.
            from rest_framework.settings import api_settings

            as_string = output and getattr(field, "coerce_to_string", api_settings.COERCE_DECIMAL_TO_STRING)
            result = ("str" if python else "string") if as_string else ("float | str" if python else "number | string")
        elif isinstance(field, serializers.FloatField):
            result = "float" if python else "number"
        elif isinstance(field, (serializers.CharField, serializers.UUIDField, serializers.DateField,
                                serializers.DateTimeField, serializers.TimeField, serializers.DurationField,
                                serializers.SlugRelatedField, serializers.HyperlinkedRelatedField,
                                serializers.StringRelatedField, serializers.FileField)):
            result = "str" if python else "string"
        else:
            # JSON and computed fields without a declared shape remain explicitly unknown.
            result = unknown
        if field.allow_null:
            result += " | None" if python else " | null"
        return result

    def choice_type(self, values: list[object]) -> str:
        """Render literal choices without losing numeric or boolean values."""
        if not values:
            return "Any" if self.language == "python" else "unknown"
        if self.language == "python":
            return "Literal[" + ", ".join(repr(value) for value in values) + "]"
        return " | ".join(json.dumps(value) for value in values)

    def render(self, routes: list[BloomerpRoute]) -> str:
        """Render each route's operations, adding verb suffixes for multiple contracts."""
        methods: list[str] = []
        names: set[str] = set()
        for route in routes:
            name = re.sub(r"[^a-zA-Z0-9_]", "_", route.url_name.removeprefix("api_"))
            if route.model is not None:
                name = f"{model_name_plural_underline(route.model)}_{name}"
            if not name or name[0].isdigit():
                name = "endpoint_" + name
            contracts = route.sdk_endpoints
            for contract in contracts:
                operation_name = f"{name}_{contract.method.lower()}" if len(contracts) > 1 else name
                parts = operation_name.split("_")
                method = operation_name if self.language == "python" else parts[0] + "".join(part.capitalize() for part in parts[1:])
                if method in names or keyword.iskeyword(method) or method in {"client", "constructor", "__init__"}:
                    raise ValueError(f"Conflicting custom SDK method: {method}")
                names.add(method)
                type_name = "Custom" + "".join(part[:1].upper() + part[1:] for part in parts)
                input_type = self.field_type(contract.resolve(contract.input_serializer, route.model), type_name + "Input", output=False)
                output_type = self.field_type(contract.resolve(contract.output_serializer, route.model), type_name + "Output", output=True)
                methods.append(self.render_method(route, contract, method, input_type, output_type))

        if self.language == "python":
            client = ['class CustomApi:', '    """Typed custom endpoints registered by the application."""',
                      '    def __init__(self, client: BloomerpHttpClient) -> None:',
                      '        """Reuse the SDK authentication and request transport."""', '        self.client = client']
        elif self.language == "typescript":
            client = ['export class CustomApi {', '  /** Reuse the SDK authentication and request transport. */',
                      '  constructor(private readonly client: BloomerpHttpClient) {}']
        else:
            client = ['export class CustomApi {', '  /** @param {BloomerpHttpClient} client Shared request transport. */',
                      '  constructor(client) { this.client = client; }']
        client.extend(methods)
        if self.language != "python":
            client.append("}")
        if self.language == "javascript":
            # JSDoc imports no TypeScript runtime; structural types remain editor-visible.
            declarations = [self.as_jsdoc(value) for value in self.types.values()]
        else:
            declarations = list(self.types.values())
        return "\n\n".join([*declarations, "\n".join(client)])

    def as_jsdoc(self, declaration: str) -> str:
        """Convert generated structural interfaces to JavaScript typedef comments."""
        header, *members, _closing = declaration.splitlines()
        name = header.split()[2]
        properties: list[str] = []
        for member in members:
            key, value = member.strip().split(": ", 1)
            optional = key.endswith("?")
            key = json.loads(key.removesuffix("?"))
            properties.append(f" * @property {{{value.removesuffix(';')}}} {'[' + key + ']' if optional else key}")
        return "/**\n * @typedef {Object} " + name + "\n" + "\n".join(properties) + "\n */"

    def render_method(
        self,
        route: BloomerpRoute,
        contract: SdkEndpoint,
        method: str,
        input_type: str,
        output_type: str,
    ) -> str:
        """Encode route arguments and send GET inputs as queries, other inputs as JSON."""
        parameters = re.findall(r"<(?:(\w+):)?(\w+)>", route.path)
        python = self.language == "python"
        path = repr(route.path) if python else json.dumps(route.path)
        fields: list[str] = []
        for converter, key in parameters:
            token = f"<{converter + ':' if converter else ''}{key}>"
            if python:
                path += f".replace({token!r}, quote(str(path_params[{key!r}]), safe={('/' if converter == 'path' else '')!r}))"
            else:
                encoded = f"encodeURIComponent(String(pathParams[{json.dumps(key)}]))"
                if converter == "path":
                    encoded += '.replace(/%2F/g, "/")'
                path += f".replace({json.dumps(token)}, {encoded})"
            kind = "number" if converter == "int" else "string | number" if converter == "int_or_uuid" else "string"
            fields.append(f"{json.dumps(key)}: {kind}")
        verb = contract.method
        if python:
            args = ", path_params: dict[str, str | int]" if parameters else ""
            argument = "query" if verb == "GET" else "data"
            return (f"\n    def {method}(self, payload: {input_type}{args}, options: BloomerpRequestOptions | None = None) -> {output_type}:\n"
                    f'        """Call {verb} {route.path}."""\n'
                    f'        return self.client.request({path}, method="{verb}", {argument}=payload, options=options)')
        args = ", pathParams: { " + "; ".join(fields) + " }" if parameters else ""
        argument = "query: payload as unknown as QueryParams" if verb == "GET" else "body: JSON.stringify(payload)"
        if self.language == "javascript":
            args = ", pathParams" if parameters else ""
            argument = "query: payload" if verb == "GET" else "body: JSON.stringify(payload)"
            path_doc = "\n   * @param {Record<string, string | number>} pathParams URL arguments." if parameters else ""
            signature = (f"  /** Call {verb} {route.path}.\n   * @param {{{input_type}}} payload Validated input.{path_doc}\n"
                         f"   * @param {{BloomerpRequestOptions}} [options] Request options.\n   * @returns {{Promise<{output_type}>}}\n   */\n"
                         f"  {method}(payload{args}, options = undefined) {{")
            request = "this.client.request"
        else:
            signature = (f"  /** Call {verb} {route.path}. */\n"
                         f"  {method}(payload: {input_type}{args}, options?: BloomerpRequestOptions): Promise<{output_type}> {{")
            request = f"this.client.request<{output_type}>"
        return f'\n{signature}\n    return {request}({path}, {{ ...options, method: "{verb}", {argument} }});\n  }}'
