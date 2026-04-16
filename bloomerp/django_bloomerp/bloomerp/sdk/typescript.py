from __future__ import annotations

import json
from pathlib import Path

from bloomerp.sdk.base import BaseSdkGenerator, SdkModelDefinition


class TypescriptSdkGenerator(BaseSdkGenerator):
    language = "typescript"
    default_filename = "index.ts"

    def render_readme(self, model_definitions: list[SdkModelDefinition]) -> str:
        example_model = self.get_example_model(model_definitions)
        model_name = example_model.class_name if example_model else "Customer"
        client_name = example_model.variable_name if example_model else "customers"
        id_type_example = '"1"' if example_model and example_model.pk_type == "string" else "1"

        create_payload = "{\n  // fill in required fields here\n}"
        filter_key = self.get_example_field_name(example_model)

        return f"""# Bloomerp TypeScript SDK

Generated SDK entry file: `{self.filename}`

## Setup

```ts
import BloomerpSdk from "./{self.filename}";

const sdk = new BloomerpSdk({{
  baseUrl: "https://example.com",
  auth: {{
    type: "basic",
    username: "admin",
    password: "password",
  }},
}});
```

## Read One

```ts
const item = await sdk.{client_name}.retrieve({id_type_example});
```

## Create

```ts
const created = await sdk.{client_name}.create({create_payload});
```

## Update

```ts
const updated = await sdk.{client_name}.update({id_type_example}, {{
  {filter_key}: "Updated value",
}});
```

## Partial Update

```ts
const patched = await sdk.{client_name}.partialUpdate({id_type_example}, {{
  {filter_key}: "Patched value",
}});
```

## Delete

```ts
await sdk.{client_name}.destroy({id_type_example});
```

## Filter / List

```ts
const results = await sdk.{client_name}.list({{
  {filter_key}: "Example",
}});
```

## Notes

- `list()` accepts plain field filters and lookup-style filters such as `field__icontains`.
- `create()`, `update()`, and `partialUpdate()` are typed from the generated Bloomerp model metadata.
- Field metadata is available via `{client_name}Fields`.
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
        return """export type QueryValue = string | number | boolean | null | undefined;
export type QueryParams = Record<string, QueryValue | QueryValue[]>;

export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export type ListResponse<T> = T[] | PaginatedResponse<T>;

export type BloomerpAuth =
  | { type: "none" }
  | { type: "basic"; username: string; password: string }
  | { type: "bearer"; token: string }
  | { type: "authorization"; value: string };

export interface BloomerpSdkConfig {
  baseUrl: string;
  auth?: BloomerpAuth;
  headers?: Record<string, string>;
  fetch?: typeof fetch;
}

export interface BloomerpFieldMetadata {
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
}

export class BloomerpHttpClient {
  private readonly baseUrl: string;
  private readonly auth: BloomerpAuth;
  private readonly headers: Record<string, string>;
  private readonly fetchImpl: typeof fetch;

  constructor(config: BloomerpSdkConfig) {
    this.baseUrl = config.baseUrl.replace(/\\/+$/, "");
    this.auth = config.auth ?? { type: "none" };
    this.headers = config.headers ?? {};
    this.fetchImpl = config.fetch ?? fetch;
  }

  async request<T>(path: string, init: RequestInit = {}, query?: QueryParams): Promise<T> {
    const url = new URL(this.baseUrl + path);
    if (query) {
      for (const [key, value] of Object.entries(query)) {
        if (value === undefined) {
          continue;
        }
        if (Array.isArray(value)) {
          for (const item of value) {
            if (item !== undefined) {
              url.searchParams.append(key, String(item));
            }
          }
          continue;
        }
        if (value !== null) {
          url.searchParams.set(key, String(value));
        }
      }
    }

    const headers = new Headers(this.headers);
    const authHeader = this.getAuthorizationHeader();
    if (authHeader) {
      headers.set("Authorization", authHeader);
    }

    const hasBody = init.body !== undefined && init.body !== null;
    if (hasBody && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }

    const response = await this.fetchImpl(url.toString(), {
      ...init,
      headers,
    });

    if (!response.ok) {
      throw new Error(`Bloomerp request failed with status ${response.status}: ${response.statusText}`);
    }

    if (response.status === 204) {
      return undefined as T;
    }

    return response.json() as Promise<T>;
  }

  private getAuthorizationHeader(): string | null {
    switch (this.auth.type) {
      case "basic":
        return `Basic ${encodeBase64(`${this.auth.username}:${this.auth.password}`)}`;
      case "bearer":
        return `Bearer ${this.auth.token}`;
      case "authorization":
        return this.auth.value;
      case "none":
      default:
        return null;
    }
  }
}

function encodeBase64(value: string): string {
  if (typeof btoa === "function") {
    return btoa(value);
  }
  const globalBuffer = (globalThis as { Buffer?: { from(input: string, encoding: string): { toString(outputEncoding: string): string } } }).Buffer;
  if (globalBuffer) {
    return globalBuffer.from(value, "utf-8").toString("base64");
  }
  throw new Error("No base64 encoder available in this runtime.");
}

export class ModelApi<TModel, TId extends string | number, TCreate, TUpdate, TFieldName extends string> {
  constructor(
    protected readonly client: BloomerpHttpClient,
    protected readonly endpoint: string,
  ) {}

  list(query?: Partial<Record<TFieldName | `${TFieldName}__${string}`, QueryValue | QueryValue[]>>): Promise<ListResponse<TModel>> {
    return this.client.request<ListResponse<TModel>>(this.endpoint, { method: "GET" }, query as QueryParams | undefined);
  }

  retrieve(id: TId): Promise<TModel> {
    return this.client.request<TModel>(`${this.endpoint}${id}/`, { method: "GET" });
  }

  create(payload: TCreate): Promise<TModel> {
    return this.client.request<TModel>(this.endpoint, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  update(id: TId, payload: TUpdate): Promise<TModel> {
    return this.client.request<TModel>(`${this.endpoint}${id}/`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  }

  partialUpdate(id: TId, payload: Partial<TUpdate>): Promise<TModel> {
    return this.client.request<TModel>(`${this.endpoint}${id}/`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  }

  destroy(id: TId): Promise<void> {
    return this.client.request<void>(`${this.endpoint}${id}/`, { method: "DELETE" });
  }
}"""

    def render_model_section(self, model_definition: SdkModelDefinition) -> str:
        field_names = [field.name for field in model_definition.fields]
        create_fields = [field for field in model_definition.fields if field.editable and field.name != "id"]

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
            f"export class {model_definition.class_name}Api extends ModelApi<{model_definition.class_name}, {model_definition.class_name}Id, {model_definition.class_name}Create, {model_definition.class_name}Update, {model_definition.class_name}FieldName> {{",
            "  constructor(client: BloomerpHttpClient) {",
            f'    super(client, "/api/{model_definition.endpoint_name}/");',
            "  }",
            "}",
        ]
        return "\n".join(model_lines)

    def render_sdk_class(self, model_definitions: list[SdkModelDefinition]) -> str:
        lines = [
            "export class BloomerpSdk {",
            "  public readonly client: BloomerpHttpClient;",
            *[
                f"  public readonly {model_definition.variable_name}: {model_definition.class_name}Api;"
                for model_definition in model_definitions
            ],
            "",
            "  constructor(config: BloomerpSdkConfig) {",
            "    this.client = new BloomerpHttpClient(config);",
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
