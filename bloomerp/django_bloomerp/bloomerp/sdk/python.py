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
        identifier_key = "email" if "session" in self.get_enabled_auth_strategy_types() else "username"
        return f"""# Bloomerp Python SDK

Generated SDK entry file: `{self.filename}`

## Setup

```python
from {self.filename.removesuffix('.py')} import BloomerpSdk

sdk = BloomerpSdk(
    base_url="https://example.com",
    auth={{
        "type": "session",
    }},
)
```

## Session Auth

```python
sdk.auth.csrf()
sdk.auth.login({{
    "{identifier_key}": "admin@example.com",
    "password": "password",
}})

session = sdk.auth.session()
```

## Read One

```python
item = sdk.{client_name}.retrieve({id_example})
print(item["{filter_key}"])
```

## Filter / List

```python
page = sdk.{client_name}.list({{
    "{filter_key}": "Example",
}})

for item in page["results"]:
    print(item["{filter_key}"])
```
"""

    def render_prelude(self) -> str:
        auth_strategy_types = repr(self.get_enabled_auth_strategy_types())
        return f"""from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from http.cookiejar import CookieJar
from typing import Any, Generic, Literal, NotRequired, TypedDict, TypeVar, cast
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener


AuthType = Literal["none", "session", "basic", "bearer", "apiKey", "authorization", "custom"]
TModel = TypeVar("TModel")
TCreate = TypeVar("TCreate")
TUpdate = TypeVar("TUpdate")
TId = TypeVar("TId", str, int)


class PaginatedResponse(TypedDict, Generic[TModel]):
    count: int
    next: str | None
    previous: str | None
    results: list[TModel]


ListResponse = PaginatedResponse[TModel]


class BloomerpSessionResponse(TypedDict, total=False):
    authenticated: bool
    user: dict[str, Any]


class BloomerpCsrfResponse(TypedDict):
    csrfToken: str


class BloomerpAuthLoginPayload(TypedDict, total=False):
    password: str
    identifier: NotRequired[str]
    username: NotRequired[str]
    email: NotRequired[str]


class BloomerpRequestOptions(TypedDict, total=False):
    headers: dict[str, str]
    query: dict[str, Any]
    timeout: float


class SessionCsrfConfig(TypedDict, total=False):
    enabled: bool
    header_name: str
    token: str | None


class BloomerpAuth(TypedDict, total=False):
    type: AuthType
    username: str
    password: str
    token: str
    value: str
    key: str
    header_name: str
    headers: dict[str, str]
    credentials: str
    csrf: SessionCsrfConfig


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


@dataclass(frozen=True)
class BloomerpHttpError(Exception):
    status: int
    status_text: str
    body: Any = None

    def __str__(self) -> str:
        return f"Bloomerp request failed with status {{self.status}}: {{self.status_text}}"


class BloomerpSdkConfig(TypedDict, total=False):
    auth: BloomerpAuth
    headers: dict[str, str]


class BloomerpHttpClient:
    def __init__(self, base_url: str, auth: BloomerpAuth | None = None, headers: dict[str, str] | None = None):
        self.base_url = base_url.rstrip("/")
        self.auth = auth or {{"type": "none"}}
        self.headers = headers or {{}}
        self.cookie_jar = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookie_jar))
        self.csrf_token: str | None = None

    def request(
        self,
        path: str,
        method: str = "GET",
        data: Any = None,
        query: dict[str, Any] | None = None,
        options: BloomerpRequestOptions | None = None,
    ) -> Any:
        options = options or {{}}
        url = self.base_url + path
        normalized_query = options.get("query") if options.get("query") is not None else query
        if normalized_query:
            params: list[tuple[str, str]] = []
            for key, value in normalized_query.items():
                if value is None:
                    continue
                if isinstance(value, (list, tuple)):
                    params.extend((key, str(item)) for item in value if item is not None)
                else:
                    params.append((key, str(value)))
            if params:
                url = f"{{url}}?{{urlencode(params)}}"

        headers = dict(self.headers)
        headers.update(self._get_auth_headers())
        headers.update(options.get("headers") or {{}})

        body = None
        if data is not None:
            headers.setdefault("Content-Type", "application/json")
            body = json.dumps(data).encode("utf-8")

        if self._should_attach_csrf(method, headers):
            headers[self._get_csrf_header_name()] = self._resolve_csrf_token()

        request = Request(url, data=body, headers=headers, method=method)

        try:
            with self.opener.open(request, timeout=options.get("timeout")) as response:
                if response.status == 204:
                    return None
                payload = response.read()
                if not payload:
                    return None
                content_type = response.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    return json.loads(payload.decode("utf-8"))
                return payload.decode("utf-8")
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8") if exc.fp else ""
            parsed_body: Any = error_body
            if error_body:
                try:
                    parsed_body = json.loads(error_body)
                except json.JSONDecodeError:
                    parsed_body = error_body
            raise BloomerpHttpError(status=exc.code, status_text=exc.reason, body=parsed_body) from exc

    def fetch_csrf_token(self, options: BloomerpRequestOptions | None = None) -> BloomerpCsrfResponse:
        response = cast(BloomerpCsrfResponse, self.request("/api/auth/csrf/", method="GET", options=options))
        self.csrf_token = response.get("csrfToken")
        return response

    def _get_auth_headers(self) -> dict[str, str]:
        auth_type = str(self.auth.get("type", "none"))
        headers: dict[str, str] = {{}}
        if auth_type == "basic":
            token = base64.b64encode(
                f"{{self.auth['username']}}:{{self.auth['password']}}".encode("utf-8")
            ).decode("ascii")
            headers["Authorization"] = f"Basic {{token}}"
        elif auth_type == "bearer":
            headers["Authorization"] = f"Bearer {{self.auth['token']}}"
        elif auth_type == "authorization":
            headers["Authorization"] = str(self.auth["value"])
        elif auth_type == "apiKey":
            headers[str(self.auth.get("header_name", "X-API-Key"))] = str(self.auth["key"])
        elif auth_type == "custom":
            headers.update(cast(dict[str, str], self.auth.get("headers", {{}})))
        return headers

    def _should_attach_csrf(self, method: str, headers: dict[str, str]) -> bool:
        if str(self.auth.get("type", "none")) != "session":
            return False
        if method.upper() in {{"GET", "HEAD", "OPTIONS", "TRACE"}}:
            return False
        csrf_config = cast(SessionCsrfConfig, self.auth.get("csrf", {{}}))
        header_name = str(csrf_config.get("header_name", "X-CSRFToken"))
        if header_name in headers:
            return False
        return bool(csrf_config.get("enabled", True))

    def _get_csrf_header_name(self) -> str:
        csrf_config = cast(SessionCsrfConfig, self.auth.get("csrf", {{}}))
        return str(csrf_config.get("header_name", "X-CSRFToken"))

    def _resolve_csrf_token(self) -> str:
        csrf_config = cast(SessionCsrfConfig, self.auth.get("csrf", {{}}))
        configured_token = csrf_config.get("token")
        if configured_token:
            return configured_token
        if self.csrf_token:
            return self.csrf_token
        response = self.fetch_csrf_token()
        return response["csrfToken"]


def normalize_list_response(value: list[TModel] | PaginatedResponse[TModel]) -> PaginatedResponse[TModel]:
    if isinstance(value, list):
        return {{
            "count": len(value),
            "next": None,
            "previous": None,
            "results": value,
        }}
    return value


class AuthApi:
    def __init__(self, client: BloomerpHttpClient):
        self.client = client

    def session(self, options: BloomerpRequestOptions | None = None) -> BloomerpSessionResponse:
        return cast(BloomerpSessionResponse, self.client.request("/api/auth/session/", method="GET", options=options))

    def csrf(self, options: BloomerpRequestOptions | None = None) -> BloomerpCsrfResponse:
        return self.client.fetch_csrf_token(options=options)

    def login(
        self,
        payload: BloomerpAuthLoginPayload | dict[str, Any],
        options: BloomerpRequestOptions | None = None,
    ) -> BloomerpSessionResponse:
        return cast(
            BloomerpSessionResponse,
            self.client.request("/api/auth/login/", method="POST", data=payload, options=options),
        )

    def logout(self, options: BloomerpRequestOptions | None = None) -> BloomerpSessionResponse:
        return cast(
            BloomerpSessionResponse,
            self.client.request("/api/auth/logout/", method="POST", options=options),
        )


class ModelApi(Generic[TModel, TId, TCreate, TUpdate]):
    def __init__(self, client: BloomerpHttpClient, endpoint: str):
        self.client = client
        self.endpoint = endpoint

    def list(
        self,
        query: dict[str, Any] | None = None,
        options: BloomerpRequestOptions | None = None,
    ) -> PaginatedResponse[TModel]:
        response = cast(
            list[TModel] | PaginatedResponse[TModel],
            self.client.request(self.endpoint, method="GET", query=query, options=options),
        )
        return normalize_list_response(response)

    def list_results(
        self,
        query: dict[str, Any] | None = None,
        options: BloomerpRequestOptions | None = None,
    ) -> list[TModel]:
        return self.list(query=query, options=options)["results"]

    def retrieve(self, object_id: TId, options: BloomerpRequestOptions | None = None) -> TModel:
        return cast(TModel, self.client.request(f"{{self.endpoint}}{{object_id}}/", method="GET", options=options))

    def create(self, payload: TCreate, options: BloomerpRequestOptions | None = None) -> TModel:
        return cast(TModel, self.client.request(self.endpoint, method="POST", data=payload, options=options))

    def update(self, object_id: TId, payload: TUpdate, options: BloomerpRequestOptions | None = None) -> TModel:
        return cast(
            TModel,
            self.client.request(f"{{self.endpoint}}{{object_id}}/", method="PUT", data=payload, options=options),
        )

    def partial_update(
        self,
        object_id: TId,
        payload: TUpdate,
        options: BloomerpRequestOptions | None = None,
    ) -> TModel:
        return cast(
            TModel,
            self.client.request(f"{{self.endpoint}}{{object_id}}/", method="PATCH", data=payload, options=options),
        )

    def destroy(self, object_id: TId, options: BloomerpRequestOptions | None = None) -> None:
        self.client.request(f"{{self.endpoint}}{{object_id}}/", method="DELETE", options=options)


bloomerp_auth_strategy_types: tuple[str, ...] = tuple({auth_strategy_types})
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
        public_access = repr(model_definition.public_access)
        capabilities = repr(model_definition.capabilities)

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
            f"{model_definition.variable_name}_capabilities: dict[str, bool] = {capabilities}",
            f"{model_definition.variable_name}_public_access: dict[str, Any] = {public_access}",
            "",
            f"class {model_definition.class_name}Api(ModelApi[{model_definition.class_name}, {model_definition.python_pk_type}, {model_definition.class_name}Create, {model_definition.class_name}Create]):",
            "    def __init__(self, client: BloomerpHttpClient):",
            f'        super().__init__(client, "/api/{model_definition.endpoint_name}/")',
        ]
        return "\n".join(lines)

    def render_sdk_class(self, model_definitions: list[SdkModelDefinition]) -> str:
        metadata_lines: list[str] = [
            "        self.metadata = {",
            "            \"auth_strategies\": bloomerp_auth_strategy_types,",
            "            \"models\": {",
        ]
        for model_definition in model_definitions:
            metadata_lines.extend(
                [
                    f"                \"{model_definition.variable_name}\": {{",
                    f"                    \"endpoint\": \"/api/{model_definition.endpoint_name}/\",",
                    f"                    \"capabilities\": {model_definition.variable_name}_capabilities,",
                    f"                    \"public_access\": {model_definition.variable_name}_public_access,",
                    f"                    \"fields\": {model_definition.variable_name}_fields,",
                    "                },",
                ]
            )
        metadata_lines.extend(
            [
                "            },",
                "        }",
            ]
        )

        lines = [
            "class BloomerpSdk:",
            "    def __init__(self, base_url: str, auth: BloomerpAuth | None = None, headers: dict[str, str] | None = None):",
            "        self.client = BloomerpHttpClient(base_url=base_url, auth=auth, headers=headers)",
            "        self.auth = AuthApi(self.client)",
            *metadata_lines,
            *[
                f"        self.{model_definition.variable_name}: {model_definition.class_name}Api = {model_definition.class_name}Api(self.client)"
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
