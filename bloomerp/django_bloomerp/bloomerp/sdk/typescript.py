from __future__ import annotations

import json

from bloomerp.sdk.base import BaseSdkGenerator, SdkModelDefinition


class TypescriptSdkGenerator(BaseSdkGenerator):
    language = "typescript"
    default_filename = "index.ts"

    def render_readme(self, model_definitions: list[SdkModelDefinition]) -> str:
        example_model = self.get_example_model(model_definitions)
        model_name = example_model.class_name if example_model else "Customer"
        client_name = example_model.variable_name if example_model else "customers"
        id_type_example = '"1"' if example_model and example_model.pk_type == "string" else "1"
        filter_key = self.get_example_field_name(example_model)

        return f"""# Bloomerp TypeScript SDK

Generated SDK entry file: `{self.filename}`

## Setup

```ts
import BloomerpSdk from "./{self.filename}";

const sdk = new BloomerpSdk({{
  baseUrl: "https://example.com",
  auth: {{
    type: "session",
    credentials: "include",
  }},
}});
```

## Session Auth

```ts
await sdk.auth.csrf();
await sdk.auth.login({{
  username: "admin",
  password: "password",
}});

const session = await sdk.auth.session();
```

## Read One

```ts
const item = await sdk.{client_name}.retrieve({id_type_example});
```

## Create

```ts
const created = await sdk.{client_name}.create({{
  // fill in required fields here
}}, {{
  headers: {{
    "X-Request-Source": "web",
  }},
}});
```

## Filter / List

```ts
const page = await sdk.{client_name}.list({{
  {filter_key}: "Example",
}}, {{
  cache: "no-store",
}});

const results = page.results;
```

## Notes

- `sdk.auth.*` targets Bloomerp's built-in `/api/auth/*` endpoints.
- `list()` always returns a paginated shape with `results`, `count`, `next`, and `previous`.
- Per-request options flow through to `fetch`, including `cache`, `credentials`, `headers`, `signal`, and framework-specific fetch options.
- Structured failures throw `BloomerpHttpError`.
- Example model shown above: `{model_name}`.
"""

    def render_source(self, model_definitions: list[SdkModelDefinition]) -> str:
        sections = [
            self.render_prelude(),
            *[self.render_model_section(model_definition) for model_definition in model_definitions],
            self.render_sdk_class(model_definitions),
        ]
        return "\n\n".join(section.rstrip() for section in sections if section).strip() + "\n"

    def render_prelude(self) -> str:
        auth_strategy_types = json.dumps(self.get_enabled_auth_strategy_types())
        return f"""export type QueryValue = string | number | boolean | null | undefined;
export type QueryParams = Record<string, QueryValue | QueryValue[]>;

export interface PaginatedResponse<T> {{
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}}

export type ListResponse<T> = PaginatedResponse<T>;

export interface BloomerpSessionResponse {{
  authenticated: boolean;
  user?: Record<string, unknown>;
}}

export interface BloomerpCsrfResponse {{
  csrfToken: string;
}}

export interface BloomerpAuthLoginPayload {{
  password: string;
  identifier?: string;
  username?: string;
  email?: string;
  [key: string]: unknown;
}}

export interface BloomerpFieldMetadata {{
  name: string;
  title: string;
  fieldType: string;
  dbFieldType: string | null;
  nullable: boolean;
  many: boolean;
  relatedModel: string | null;
  editable: boolean;
  requiredOnCreate: boolean;
  tsType: string;
}}

export interface BloomerpModelPublicAccessMetadata {{
  listAllowed: boolean;
  readAllowed: boolean;
  listFields: string[] | null;
  readFields: string[] | null;
  authenticatedFallbackEnabled: boolean;
}}

export interface BloomerpModelCapabilities {{
  list: boolean;
  retrieve: boolean;
  create: boolean;
  update: boolean;
  partialUpdate: boolean;
  destroy: boolean;
}}

export interface BloomerpRequestOptions extends Omit<RequestInit, "headers"> {{
  headers?: HeadersInit;
  query?: QueryParams;
  fetchOptions?: Record<string, unknown>;
}}

export interface BloomerpSessionCsrfConfig {{
  enabled?: boolean;
  headerName?: string;
  token?: string | null | (() => string | null | Promise<string | null>);
}}

export type BloomerpAuth =
  | {{ type: "none" }}
  | {{ type: "session"; credentials?: RequestCredentials; csrf?: BloomerpSessionCsrfConfig }}
  | {{ type: "basic"; username: string; password: string }}
  | {{ type: "bearer"; token: string }}
  | {{ type: "apiKey"; key: string; headerName?: string }}
  | {{ type: "authorization"; value: string }}
  | {{ type: "custom"; headers?: Record<string, string> }};

export interface BloomerpSdkConfig {{
  baseUrl: string;
  auth?: BloomerpAuth;
  headers?: Record<string, string>;
  fetch?: typeof fetch;
}}

export class BloomerpHttpError<TBody = unknown> extends Error {{
  public readonly status: number;
  public readonly statusText: string;
  public readonly body: TBody | undefined;
  public readonly headers: Headers;

  constructor(response: Response, body?: TBody) {{
    super(`Bloomerp request failed with status ${{response.status}}: ${{response.statusText}}`);
    this.name = "BloomerpHttpError";
    this.status = response.status;
    this.statusText = response.statusText;
    this.body = body;
    this.headers = response.headers;
  }}
}}

export class BloomerpHttpClient {{
  private readonly baseUrl: string;
  private readonly auth: BloomerpAuth;
  private readonly headers: Record<string, string>;
  private readonly fetchImpl: typeof fetch;
  private csrfToken: string | null = null;

  constructor(config: BloomerpSdkConfig) {{
    this.baseUrl = config.baseUrl.replace(/\\/+$/, "");
    this.auth = config.auth ?? {{ type: "none" }};
    this.headers = config.headers ?? {{}};
    this.fetchImpl = config.fetch ?? fetch;
  }}

  async request<T>(path: string, options: BloomerpRequestOptions = {{}}): Promise<T> {{
    const {{ query, fetchOptions, headers: requestHeaders, ...init }} = options;
    const url = this.buildUrl(path, query);
    const headers = this.buildHeaders(requestHeaders);

    this.applyAuthHeaders(headers);

    if (this.shouldSetJsonContentType(init.body, headers)) {{
      headers.set("Content-Type", "application/json");
    }}

    const method = (init.method ?? "GET").toUpperCase();
    if (await this.shouldAttachCsrfHeader(method, headers)) {{
      const csrfToken = await this.resolveCsrfToken();
      if (csrfToken) {{
        headers.set(this.getCsrfHeaderName(), csrfToken);
      }}
    }}

    const response = await this.fetchImpl(url.toString(), {{
      ...(fetchOptions ?? {{}}),
      ...init,
      credentials: this.resolveCredentials(init.credentials),
      headers,
    }} as RequestInit);

    const body = await this.parseResponseBody(response);
    if (!response.ok) {{
      throw new BloomerpHttpError(response, body);
    }}

    return body as T;
  }}

  async fetchCsrfToken(options: BloomerpRequestOptions = {{}}): Promise<BloomerpCsrfResponse> {{
    const response = await this.request<BloomerpCsrfResponse>("/api/auth/csrf/", {{
      ...options,
      method: options.method ?? "GET",
    }});
    this.csrfToken = response.csrfToken ?? null;
    return response;
  }}

  private buildUrl(path: string, query?: QueryParams): URL {{
    const url = new URL(this.baseUrl + path);
    if (!query) {{
      return url;
    }}

    for (const [key, value] of Object.entries(query)) {{
      if (value === undefined) {{
        continue;
      }}
      if (Array.isArray(value)) {{
        for (const item of value) {{
          if (item !== undefined && item !== null) {{
            url.searchParams.append(key, String(item));
          }}
        }}
        continue;
      }}
      if (value !== null) {{
        url.searchParams.set(key, String(value));
      }}
    }}

    return url;
  }}

  private buildHeaders(requestHeaders?: HeadersInit): Headers {{
    const headers = new Headers(this.headers);
    if (requestHeaders) {{
      new Headers(requestHeaders).forEach((value, key) => headers.set(key, value));
    }}
    return headers;
  }}

  private applyAuthHeaders(headers: Headers): void {{
    const authHeader = this.getAuthorizationHeader();
    if (authHeader) {{
      headers.set("Authorization", authHeader);
    }}

    if (this.auth.type === "apiKey") {{
      headers.set(this.auth.headerName ?? "X-API-Key", this.auth.key);
    }}

    if (this.auth.type === "custom" && this.auth.headers) {{
      for (const [key, value] of Object.entries(this.auth.headers)) {{
        headers.set(key, value);
      }}
    }}
  }}

  private shouldSetJsonContentType(body: BodyInit | null | undefined, headers: Headers): boolean {{
    return body !== undefined && body !== null && !headers.has("Content-Type");
  }}

  private getAuthorizationHeader(): string | null {{
    switch (this.auth.type) {{
      case "basic":
        return `Basic ${{encodeBase64(`${{this.auth.username}}:${{this.auth.password}}`)}}`;
      case "bearer":
        return `Bearer ${{this.auth.token}}`;
      case "authorization":
        return this.auth.value;
      default:
        return null;
    }}
  }}

  private resolveCredentials(requestCredentials?: RequestCredentials): RequestCredentials | undefined {{
    if (requestCredentials) {{
      return requestCredentials;
    }}
    if (this.auth.type === "session") {{
      return this.auth.credentials ?? "include";
    }}
    return undefined;
  }}

  private async shouldAttachCsrfHeader(method: string, headers: Headers): Promise<boolean> {{
    if (this.auth.type !== "session") {{
      return false;
    }}
    if (["GET", "HEAD", "OPTIONS", "TRACE"].includes(method)) {{
      return false;
    }}
    if (headers.has(this.getCsrfHeaderName())) {{
      return false;
    }}
    return this.auth.csrf?.enabled !== false;
  }}

  private getCsrfHeaderName(): string {{
    if (this.auth.type === "session") {{
      return this.auth.csrf?.headerName ?? "X-CSRFToken";
    }}
    return "X-CSRFToken";
  }}

  private async resolveCsrfToken(): Promise<string | null> {{
    if (this.auth.type !== "session") {{
      return null;
    }}

    const configuredToken = this.auth.csrf?.token;
    if (typeof configuredToken === "function") {{
      return (await configuredToken()) ?? null;
    }}
    if (typeof configuredToken === "string") {{
      return configuredToken;
    }}
    if (this.csrfToken) {{
      return this.csrfToken;
    }}

    const response = await this.fetchCsrfToken();
    return response.csrfToken ?? null;
  }}

  private async parseResponseBody(response: Response): Promise<unknown> {{
    if (response.status === 204) {{
      return undefined;
    }}

    const contentType = response.headers.get("content-type") ?? "";
    const rawBody = await response.text();
    if (!rawBody) {{
      return undefined;
    }}

    if (contentType.includes("application/json")) {{
      try {{
        return JSON.parse(rawBody);
      }} catch (_error) {{
        return rawBody;
      }}
    }}

    return rawBody;
  }}
}}

function encodeBase64(value: string): string {{
  if (typeof btoa === "function") {{
    return btoa(value);
  }}
  const globalBuffer = (globalThis as {{ Buffer?: {{ from(input: string, encoding: string): {{ toString(outputEncoding: string): string }} }} }}).Buffer;
  if (globalBuffer) {{
    return globalBuffer.from(value, "utf-8").toString("base64");
  }}
  throw new Error("No base64 encoder available in this runtime.");
}}

function isPaginatedResponse<T>(value: unknown): value is PaginatedResponse<T> {{
  if (!value || typeof value !== "object") {{
    return false;
  }}
  const candidate = value as Partial<PaginatedResponse<T>>;
  return (
    typeof candidate.count === "number"
    && "results" in candidate
    && Array.isArray(candidate.results)
  );
}}

function normalizeListResponse<T>(value: T[] | PaginatedResponse<T>): PaginatedResponse<T> {{
  if (Array.isArray(value)) {{
    return {{
      count: value.length,
      next: null,
      previous: null,
      results: value,
    }};
  }}
  return value;
}}

export class AuthApi {{
  constructor(private readonly client: BloomerpHttpClient) {{}}

  session(options?: BloomerpRequestOptions): Promise<BloomerpSessionResponse> {{
    return this.client.request<BloomerpSessionResponse>("/api/auth/session/", {{
      ...options,
      method: "GET",
    }});
  }}

  csrf(options?: BloomerpRequestOptions): Promise<BloomerpCsrfResponse> {{
    return this.client.fetchCsrfToken(options);
  }}

  login(payload: BloomerpAuthLoginPayload, options?: BloomerpRequestOptions): Promise<BloomerpSessionResponse> {{
    return this.client.request<BloomerpSessionResponse>("/api/auth/login/", {{
      ...options,
      method: "POST",
      body: JSON.stringify(payload),
    }});
  }}

  logout(options?: BloomerpRequestOptions): Promise<BloomerpSessionResponse> {{
    return this.client.request<BloomerpSessionResponse>("/api/auth/logout/", {{
      ...options,
      method: "POST",
    }});
  }}
}}

export class ModelApi<TModel, TId extends string | number, TCreate, TUpdate, TQuery, TFieldName extends string> {{
  constructor(
    protected readonly client: BloomerpHttpClient,
    protected readonly endpoint: string,
  ) {{}}

  async list(query?: TQuery, options?: BloomerpRequestOptions): Promise<ListResponse<TModel>> {{
    const response = await this.client.request<TModel[] | PaginatedResponse<TModel>>(this.endpoint, {{
      ...options,
      method: "GET",
      query: query as QueryParams | undefined,
    }});
    return normalizeListResponse(response);
  }}

  async listResults(query?: TQuery, options?: BloomerpRequestOptions): Promise<TModel[]> {{
    const response = await this.list(query, options);
    return response.results;
  }}

  retrieve(id: TId, options?: BloomerpRequestOptions): Promise<TModel> {{
    return this.client.request<TModel>(`${{this.endpoint}}${{id}}/`, {{
      ...options,
      method: "GET",
    }});
  }}

  create(payload: TCreate, options?: BloomerpRequestOptions): Promise<TModel> {{
    return this.client.request<TModel>(this.endpoint, {{
      ...options,
      method: "POST",
      body: JSON.stringify(payload),
    }});
  }}

  update(id: TId, payload: TUpdate, options?: BloomerpRequestOptions): Promise<TModel> {{
    return this.client.request<TModel>(`${{this.endpoint}}${{id}}/`, {{
      ...options,
      method: "PUT",
      body: JSON.stringify(payload),
    }});
  }}

  partialUpdate(id: TId, payload: Partial<TUpdate>, options?: BloomerpRequestOptions): Promise<TModel> {{
    return this.client.request<TModel>(`${{this.endpoint}}${{id}}/`, {{
      ...options,
      method: "PATCH",
      body: JSON.stringify(payload),
    }});
  }}

  destroy(id: TId, options?: BloomerpRequestOptions): Promise<void> {{
    return this.client.request<void>(`${{this.endpoint}}${{id}}/`, {{
      ...options,
      method: "DELETE",
    }});
  }}
}}

export const bloomerpAuthStrategyTypes = {auth_strategy_types} as const;
"""

    def render_model_section(self, model_definition: SdkModelDefinition) -> str:
        field_names = [field.name for field in model_definition.fields]
        create_fields = [field for field in model_definition.fields if field.editable and field.name != "id"]
        public_access = json.dumps(model_definition.public_access)
        capabilities = json.dumps(model_definition.capabilities)

        model_lines = [
            f"export interface {model_definition.class_name} {{",
            *[
                f"  {field.name}: {field.ts_type};"
                for field in model_definition.fields
            ],
            "}",
            "",
            f"export type {model_definition.class_name}Id = {model_definition.pk_type};",
            f"export type {model_definition.class_name}FieldName = {self.render_union(field_names)};",
            "",
            f"export interface {model_definition.class_name}Create {{",
            *[
                (
                    f"  {field.name}: {field.ts_type};"
                    if field.required_on_create
                    else f"  {field.name}?: {field.ts_type};"
                )
                for field in create_fields
            ],
            "}",
            "",
            f"export type {model_definition.class_name}Update = Partial<{model_definition.class_name}Create>;",
            f"export type {model_definition.class_name}Query = Partial<Record<{model_definition.class_name}FieldName | `${{{model_definition.class_name}FieldName}}__${{string}}`, QueryValue | QueryValue[]>>;",
            "",
            f"export const {model_definition.variable_name}Fields: Record<{model_definition.class_name}FieldName, BloomerpFieldMetadata> = {{",
            *[
                "  "
                + json.dumps(field.name)
                + ": "
                + json.dumps(self.serialize_field_metadata(field))
                + ","
                for field in model_definition.fields
            ],
            "} as const;",
            "",
            f"export const {model_definition.variable_name}Capabilities: BloomerpModelCapabilities = {capabilities} as const;",
            f"export const {model_definition.variable_name}PublicAccess: BloomerpModelPublicAccessMetadata = {public_access} as const;",
            "",
            f"export class {model_definition.class_name}Api extends ModelApi<{model_definition.class_name}, {model_definition.class_name}Id, {model_definition.class_name}Create, {model_definition.class_name}Update, {model_definition.class_name}Query, {model_definition.class_name}FieldName> {{",
            "  constructor(client: BloomerpHttpClient) {",
            f'    super(client, "/api/{model_definition.endpoint_name}/");',
            "  }",
            "}",
        ]
        return "\n".join(model_lines)

    def render_sdk_class(self, model_definitions: list[SdkModelDefinition]) -> str:
        model_metadata_lines: list[str] = []
        for model_definition in model_definitions:
            model_metadata_lines.extend(
                [
                    f"      {model_definition.variable_name}: {{",
                    f"        endpoint: \"/api/{model_definition.endpoint_name}/\",",
                    f"        capabilities: {model_definition.variable_name}Capabilities,",
                    f"        publicAccess: {model_definition.variable_name}PublicAccess,",
                    f"        fields: {model_definition.variable_name}Fields,",
                    "      },",
                ]
            )
        metadata_lines = [
            "  public readonly metadata = {",
            "    authStrategies: bloomerpAuthStrategyTypes,",
            "    models: {",
            *model_metadata_lines,
            "    },",
            "  } as const;",
        ]
        lines = [
            "export class BloomerpSdk {",
            "  public readonly client: BloomerpHttpClient;",
            "  public readonly auth: AuthApi;",
            *metadata_lines,
            *[
                f"  public readonly {model_definition.variable_name}: {model_definition.class_name}Api;"
                for model_definition in model_definitions
            ],
            "",
            "  constructor(config: BloomerpSdkConfig) {",
            "    this.client = new BloomerpHttpClient(config);",
            "    this.auth = new AuthApi(this.client);",
            *[
                f"    this.{model_definition.variable_name} = new {model_definition.class_name}Api(this.client);"
                for model_definition in model_definitions
            ],
            "  }",
            "}",
            "",
            "export default BloomerpSdk;",
        ]
        return "\n".join(lines)

    def render_union(self, values: list[str]) -> str:
        if not values:
            return "never"
        return " | ".join(json.dumps(value) for value in values)
