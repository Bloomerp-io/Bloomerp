from __future__ import annotations

import json

from bloomerp.sdk.base import BaseSdkGenerator, SdkModelDefinition


class PythonSdkGenerator(BaseSdkGenerator):
    language = "python"
    default_filename = "sdk.py"

    def render_source(self, model_definitions: list[SdkModelDefinition]) -> str:
        sections = [
            self.render_prelude(),
            *[self.render_model_section(model_definition) for model_definition in model_definitions],
            self.render_sdk_class(model_definitions),
        ]
        return "\n\n".join(section.rstrip() for section in sections if section).strip() + "\n"

    def render_readme(self, model_definitions: list[SdkModelDefinition]) -> str:
        example_model = self.get_example_model(model_definitions)
        client_name = example_model.variable_name if example_model else "customers"
        filter_key = self.get_example_field_name(example_model)
        id_example = self.get_example_id_value(example_model, quoted=False)
        return f"""# Bloomerp Python SDK

Generated SDK entry file: `{self.filename}`

## Setup

```python
from {self.filename.removesuffix('.py')} import BloomerpSdk

sdk = BloomerpSdk(
    base_url="https://example.com",
    auth={{
        "type": "basic",
        "username": "admin",
        "password": "password",
    }},
)
```

## Read One

```python
item = sdk.{client_name}.retrieve({id_example})
```

## Create

```python
created = sdk.{client_name}.create({{
    # fill in required fields here
}})
```

## Update

```python
updated = sdk.{client_name}.update({id_example}, {{
    "{filter_key}": "Updated value",
}})
```

## Partial Update

```python
patched = sdk.{client_name}.partial_update({id_example}, {{
    "{filter_key}": "Patched value",
}})
```

## Delete

```python
sdk.{client_name}.destroy({id_example})
```

## Filter / List

```python
results = sdk.{client_name}.list({{
    "{filter_key}": "Example",
}})
```
"""

    def render_prelude(self) -> str:
        return """from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Literal, TypedDict
from urllib.parse import urlencode
from urllib.request import Request, urlopen


AuthType = Literal["none", "basic", "bearer", "authorization"]


@dataclass(frozen=True)
class BloomerpFieldMetadata:
    name: str
    title: str
    field_type: str
    db_field_type: str | None
    nullable: bool
    many: bool
    related_model: str | None
    editable: bool
    required_on_create: bool
    ts_type: str


class BloomerpSdkConfig(TypedDict, total=False):
    auth: dict[str, Any]
    headers: dict[str, str]


class BloomerpHttpClient:
    def __init__(self, base_url: str, auth: dict[str, Any] | None = None, headers: dict[str, str] | None = None):
        self.base_url = base_url.rstrip("/")
        self.auth = auth or {"type": "none"}
        self.headers = headers or {}

    def request(self, path: str, method: str = "GET", data: Any = None, query: dict[str, Any] | None = None):
        url = self.base_url + path
        if query:
            normalized: list[tuple[str, str]] = []
            for key, value in query.items():
                if value is None:
                    continue
                if isinstance(value, (list, tuple)):
                    normalized.extend((key, str(item)) for item in value if item is not None)
                else:
                    normalized.append((key, str(value)))
            if normalized:
                url = f"{url}?{urlencode(normalized)}"

        headers = dict(self.headers)
        auth_header = self.get_authorization_header()
        if auth_header:
            headers["Authorization"] = auth_header

        body = None
        if data is not None:
            headers.setdefault("Content-Type", "application/json")
            body = json.dumps(data).encode("utf-8")

        request = Request(url, data=body, headers=headers, method=method)
        with urlopen(request) as response:
            if response.status == 204:
                return None
            payload = response.read()
            if not payload:
                return None
            return json.loads(payload.decode("utf-8"))

    def get_authorization_header(self) -> str | None:
        auth_type = str(self.auth.get("type", "none"))
        if auth_type == "basic":
            token = base64.b64encode(
                f"{self.auth['username']}:{self.auth['password']}".encode("utf-8")
            ).decode("ascii")
            return f"Basic {token}"
        if auth_type == "bearer":
            return f"Bearer {self.auth['token']}"
        if auth_type == "authorization":
            return str(self.auth["value"])
        return None


class ModelApi:
    def __init__(self, client: BloomerpHttpClient, endpoint: str):
        self.client = client
        self.endpoint = endpoint

    def list(self, query: dict[str, Any] | None = None):
        return self.client.request(self.endpoint, method="GET", query=query)

    def retrieve(self, object_id):
        return self.client.request(f"{self.endpoint}{object_id}/", method="GET")

    def create(self, payload: dict[str, Any]):
        return self.client.request(self.endpoint, method="POST", data=payload)

    def update(self, object_id, payload: dict[str, Any]):
        return self.client.request(f"{self.endpoint}{object_id}/", method="PUT", data=payload)

    def partial_update(self, object_id, payload: dict[str, Any]):
        return self.client.request(f"{self.endpoint}{object_id}/", method="PATCH", data=payload)

    def destroy(self, object_id):
        return self.client.request(f"{self.endpoint}{object_id}/", method="DELETE")
"""

    def render_model_section(self, model_definition: SdkModelDefinition) -> str:
        model_fields = [
            f"    {field.name}: {field.python_type}"
            for field in model_definition.fields
        ] or ["    pass"]
        create_fields = [
            f"    {field.name}: {field.python_type}"
            for field in model_definition.fields
            if field.editable and field.name != "id"
        ] or ["    pass"]

        lines = [
            f"class {model_definition.class_name}(TypedDict, total=False):",
            *model_fields,
            "",
            f"class {model_definition.class_name}Create(TypedDict, total=False):",
            *create_fields,
            "",
            f"{model_definition.variable_name}_fields: dict[str, BloomerpFieldMetadata] = {{",
            *[
                f"    {json.dumps(field.name)}: BloomerpFieldMetadata(**{repr(self._python_metadata_kwargs(field))}),"
                for field in model_definition.fields
            ],
            "}",
            "",
            f"class {model_definition.class_name}Api(ModelApi):",
            "    def __init__(self, client: BloomerpHttpClient):",
            f'        super().__init__(client, "/api/{model_definition.endpoint_name}/")',
        ]
        return "\n".join(lines)

    def render_sdk_class(self, model_definitions: list[SdkModelDefinition]) -> str:
        lines = [
            "class BloomerpSdk:",
            "    def __init__(self, base_url: str, auth: dict[str, Any] | None = None, headers: dict[str, str] | None = None):",
            "        self.client = BloomerpHttpClient(base_url=base_url, auth=auth, headers=headers)",
            *[
                f"        self.{model_definition.variable_name} = {model_definition.class_name}Api(self.client)"
                for model_definition in model_definitions
            ],
        ]
        return "\n".join(lines)

    def _python_metadata_kwargs(self, field) -> dict[str, object]:
        metadata = self.serialize_field_metadata(field)
        return {
            "name": metadata["name"],
            "title": metadata["title"],
            "field_type": metadata["fieldType"],
            "db_field_type": metadata["dbFieldType"],
            "nullable": metadata["nullable"],
            "many": metadata["many"],
            "related_model": metadata["relatedModel"],
            "editable": metadata["editable"],
            "required_on_create": metadata["requiredOnCreate"],
            "ts_type": metadata["tsType"],
        }
