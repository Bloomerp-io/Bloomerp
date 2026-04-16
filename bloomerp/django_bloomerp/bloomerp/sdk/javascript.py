from __future__ import annotations

import json

from bloomerp.sdk.base import BaseSdkGenerator, SdkModelDefinition


class JavaScriptSdkGenerator(BaseSdkGenerator):
    language = "javascript"
    default_filename = "index.js"

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
        return f"""# Bloomerp JavaScript SDK

Generated SDK entry file: `{self.filename}`

## Setup

```js
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

```js
await sdk.auth.csrf();
await sdk.auth.login({{
  email: "admin@example.com",
  password: "password",
}});

const session = await sdk.auth.session();
```

## Filter / List

```js
const page = await sdk.{client_name}.list({{
  {filter_key}: "Example",
}});

for (const item of page.results) {{
  console.log(item.{filter_key});
}}
```
"""

    def render_prelude(self) -> str:
        auth_strategy_types = json.dumps(self.get_enabled_auth_strategy_types())
        return f"""/**
 * @typedef {{string | number | boolean | null | undefined}} QueryValue
 * @typedef {{Record<string, QueryValue | QueryValue[]>}} QueryParams
 *
 * @typedef {{count: number, next: string | null, previous: string | null, results: Array<any>}} PaginatedResponse
 * @typedef {{
 *   authenticated: boolean,
 *   user?: Record<string, unknown>
 * }} BloomerpSessionResponse
 * @typedef {{ csrfToken: string }} BloomerpCsrfResponse
 * @typedef {{
 *   password: string,
 *   identifier?: string,
 *   username?: string,
 *   email?: string
 * }} BloomerpAuthLoginPayload
 * @typedef {{
 *   headers?: HeadersInit,
 *   query?: QueryParams,
 *   credentials?: RequestCredentials,
 *   signal?: AbortSignal | null,
 *   cache?: RequestCache,
 *   fetchOptions?: Record<string, unknown>
 * }} BloomerpRequestOptions
 * @typedef {{
 *   enabled?: boolean,
 *   headerName?: string,
 *   token?: string | null
 * }} SessionCsrfConfig
 * @typedef {{
 *   type?: "none" | "session" | "basic" | "bearer" | "apiKey" | "authorization" | "custom",
 *   username?: string,
 *   password?: string,
 *   token?: string,
 *   key?: string,
 *   headerName?: string,
 *   value?: string,
 *   headers?: Record<string, string>,
 *   credentials?: RequestCredentials,
 *   csrf?: SessionCsrfConfig
 * }} BloomerpAuth
 */

export class BloomerpHttpError extends Error {{
  constructor(response, body = undefined) {{
    super(`Bloomerp request failed with status ${{response.status}}: ${{response.statusText}}`);
    this.name = "BloomerpHttpError";
    this.status = response.status;
    this.statusText = response.statusText;
    this.body = body;
    this.headers = response.headers;
  }}
}}

export class BloomerpHttpClient {{
  constructor(config) {{
    this.baseUrl = String(config.baseUrl || "").replace(/\\/+$/, "");
    this.auth = config.auth || {{ type: "none" }};
    this.headers = config.headers || {{}};
    this.fetchImpl = config.fetch || fetch;
    this.csrfToken = null;
  }}

  async request(path, options = {{}}) {{
    const {{ query, fetchOptions, headers: requestHeaders, ...init }} = options;
    const url = new URL(this.baseUrl + path);

    if (query) {{
      for (const [key, value] of Object.entries(query)) {{
        if (value === undefined) continue;
        if (Array.isArray(value)) {{
          for (const item of value) {{
            if (item !== undefined && item !== null) url.searchParams.append(key, String(item));
          }}
          continue;
        }}
        if (value !== null) {{
          url.searchParams.set(key, String(value));
        }}
      }}
    }}

    const headers = new Headers(this.headers);
    if (requestHeaders) {{
      new Headers(requestHeaders).forEach((value, key) => headers.set(key, value));
    }}

    this.applyAuthHeaders(headers);

    const hasBody = init.body !== undefined && init.body !== null;
    if (hasBody && !headers.has("Content-Type")) {{
      headers.set("Content-Type", "application/json");
    }}

    const method = String(init.method || "GET").toUpperCase();
    if (await this.shouldAttachCsrf(method, headers)) {{
      headers.set(this.getCsrfHeaderName(), await this.resolveCsrfToken());
    }}

    const response = await this.fetchImpl(url.toString(), {{
      ...(fetchOptions || {{}}),
      ...init,
      credentials: init.credentials || this.resolveCredentials(),
      headers,
    }});

    const body = await this.parseResponseBody(response);
    if (!response.ok) {{
      throw new BloomerpHttpError(response, body);
    }}
    return body;
  }}

  async fetchCsrfToken(options = undefined) {{
    const response = await this.request("/api/auth/csrf/", {{
      ...(options || {{}}),
      method: "GET",
    }});
    this.csrfToken = response && response.csrfToken ? response.csrfToken : null;
    return response;
  }}

  applyAuthHeaders(headers) {{
    switch (this.auth.type) {{
      case "basic":
        headers.set("Authorization", `Basic ${{encodeBase64(`${{this.auth.username}}:${{this.auth.password}}`)}}`);
        break;
      case "bearer":
        headers.set("Authorization", `Bearer ${{this.auth.token}}`);
        break;
      case "apiKey":
        headers.set(this.auth.headerName || "X-API-Key", this.auth.key);
        break;
      case "authorization":
        headers.set("Authorization", this.auth.value);
        break;
      case "custom":
        if (this.auth.headers) {{
          for (const [key, value] of Object.entries(this.auth.headers)) {{
            headers.set(key, value);
          }}
        }}
        break;
      default:
        break;
    }}
  }}

  resolveCredentials() {{
    if (this.auth.type === "session") {{
      return this.auth.credentials || "include";
    }}
    return undefined;
  }}

  async shouldAttachCsrf(method, headers) {{
    if (this.auth.type !== "session") return false;
    if (["GET", "HEAD", "OPTIONS", "TRACE"].includes(method)) return false;
    const headerName = this.getCsrfHeaderName();
    if (headers.has(headerName)) return false;
    return !this.auth.csrf || this.auth.csrf.enabled !== false;
  }}

  getCsrfHeaderName() {{
    if (this.auth.type === "session" && this.auth.csrf && this.auth.csrf.headerName) {{
      return this.auth.csrf.headerName;
    }}
    return "X-CSRFToken";
  }}

  async resolveCsrfToken() {{
    if (this.auth.type !== "session") return "";
    if (this.auth.csrf && this.auth.csrf.token) return this.auth.csrf.token;
    if (this.csrfToken) return this.csrfToken;
    const response = await this.fetchCsrfToken();
    return response.csrfToken;
  }}

  async parseResponseBody(response) {{
    if (response.status === 204) {{
      return undefined;
    }}
    const contentType = response.headers.get("content-type") || "";
    const raw = await response.text();
    if (!raw) {{
      return undefined;
    }}
    if (contentType.includes("application/json")) {{
      try {{
        return JSON.parse(raw);
      }} catch (_error) {{
        return raw;
      }}
    }}
    return raw;
  }}
}}

function encodeBase64(value) {{
  if (typeof btoa === "function") {{
    return btoa(value);
  }}
  if (typeof Buffer !== "undefined") {{
    return Buffer.from(value, "utf-8").toString("base64");
  }}
  throw new Error("No base64 encoder available in this runtime.");
}}

function normalizeListResponse(value) {{
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
  constructor(client) {{
    this.client = client;
  }}

  session(options = undefined) {{
    return this.client.request("/api/auth/session/", {{
      ...(options || {{}}),
      method: "GET",
    }});
  }}

  csrf(options = undefined) {{
    return this.client.fetchCsrfToken(options);
  }}

  login(payload, options = undefined) {{
    return this.client.request("/api/auth/login/", {{
      ...(options || {{}}),
      method: "POST",
      body: JSON.stringify(payload),
    }});
  }}

  logout(options = undefined) {{
    return this.client.request("/api/auth/logout/", {{
      ...(options || {{}}),
      method: "POST",
    }});
  }}
}}

export class ModelApi {{
  constructor(client, endpoint) {{
    this.client = client;
    this.endpoint = endpoint;
  }}

  list(query = undefined, options = undefined) {{
    return this.client.request(this.endpoint, {{
      ...(options || {{}}),
      method: "GET",
      query,
    }}).then(normalizeListResponse);
  }}

  listResults(query = undefined, options = undefined) {{
    return this.list(query, options).then((page) => page.results);
  }}

  retrieve(id, options = undefined) {{
    return this.client.request(`${{this.endpoint}}${{id}}/`, {{
      ...(options || {{}}),
      method: "GET",
    }});
  }}

  create(payload, options = undefined) {{
    return this.client.request(this.endpoint, {{
      ...(options || {{}}),
      method: "POST",
      body: JSON.stringify(payload),
    }});
  }}

  update(id, payload, options = undefined) {{
    return this.client.request(`${{this.endpoint}}${{id}}/`, {{
      ...(options || {{}}),
      method: "PUT",
      body: JSON.stringify(payload),
    }});
  }}

  partialUpdate(id, payload, options = undefined) {{
    return this.client.request(`${{this.endpoint}}${{id}}/`, {{
      ...(options || {{}}),
      method: "PATCH",
      body: JSON.stringify(payload),
    }});
  }}

  destroy(id, options = undefined) {{
    return this.client.request(`${{this.endpoint}}${{id}}/`, {{
      ...(options || {{}}),
      method: "DELETE",
    }});
  }}
}}

export const bloomerpAuthStrategyTypes = {auth_strategy_types};
"""

    def render_model_section(self, model_definition: SdkModelDefinition) -> str:
        public_access = json.dumps(model_definition.public_access)
        capabilities = json.dumps(model_definition.capabilities)
        field_typedef_lines = [
            "/**",
            f" * @typedef {{object}} {model_definition.class_name}",
            *[
                f" * @property {{{field.js_doc_type}}} {field.name}"
                for field in model_definition.fields
            ],
            " */",
            "",
            "/**",
            f" * @typedef {{object}} {model_definition.class_name}Create",
            *[
                f" * @property {{{field.js_doc_type}}} {field.name}"
                for field in model_definition.fields
                if field.editable and field.name != "id"
            ],
            " */",
            "",
        ]
        lines = [
            *field_typedef_lines,
            f"export const {model_definition.variable_name}Fields = {{",
            *[
                f"  {json.dumps(field.name)}: {json.dumps(self.serialize_field_metadata(field))},"
                for field in model_definition.fields
            ],
            "};",
            f"export const {model_definition.variable_name}Capabilities = {capabilities};",
            f"export const {model_definition.variable_name}PublicAccess = {public_access};",
            "",
            f"export class {model_definition.class_name}Api extends ModelApi {{",
            "  constructor(client) {",
            f'    super(client, "/api/{model_definition.endpoint_name}/");',
            "  }",
            "}",
        ]
        return "\n".join(lines)

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

        lines = [
            "export class BloomerpSdk {",
            "  constructor(config) {",
            "    this.client = new BloomerpHttpClient(config);",
            "    this.auth = new AuthApi(this.client);",
            "    this.metadata = {",
            "      authStrategies: bloomerpAuthStrategyTypes,",
            "      models: {",
            *model_metadata_lines,
            "      },",
            "    };",
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
