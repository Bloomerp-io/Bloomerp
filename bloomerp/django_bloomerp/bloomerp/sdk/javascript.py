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
    type: "basic",
    username: "admin",
    password: "password",
  }},
}});
```

## Read One

```js
const item = await sdk.{client_name}.retrieve({id_example});
```

## Create

```js
const created = await sdk.{client_name}.create({{
  // fill in required fields here
}});
```

## Update

```js
const updated = await sdk.{client_name}.update({id_example}, {{
  {filter_key}: "Updated value",
}});
```

## Partial Update

```js
const patched = await sdk.{client_name}.partialUpdate({id_example}, {{
  {filter_key}: "Patched value",
}});
```

## Delete

```js
await sdk.{client_name}.destroy({id_example});
```

## Filter / List

```js
const results = await sdk.{client_name}.list({{
  {filter_key}: "Example",
}});
```
"""

    def render_prelude(self) -> str:
        return """/**
 * @typedef {"none" | "basic" | "bearer" | "authorization"} AuthType
 */

export class BloomerpHttpClient {
  constructor(config) {
    this.baseUrl = String(config.baseUrl || "").replace(/\\/+$/, "");
    this.auth = config.auth || { type: "none" };
    this.headers = config.headers || {};
    this.fetchImpl = config.fetch || fetch;
  }

  async request(path, init = {}, query = undefined) {
    const url = new URL(this.baseUrl + path);
    if (query) {
      for (const [key, value] of Object.entries(query)) {
        if (value === undefined) continue;
        if (Array.isArray(value)) {
          for (const item of value) {
            if (item !== undefined) url.searchParams.append(key, String(item));
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
      return undefined;
    }

    return response.json();
  }

  getAuthorizationHeader() {
    switch (this.auth.type) {
      case "basic":
        return `Basic ${encodeBase64(`${this.auth.username}:${this.auth.password}`)}`;
      case "bearer":
        return `Bearer ${this.auth.token}`;
      case "authorization":
        return this.auth.value;
      default:
        return null;
    }
  }
}

function encodeBase64(value) {
  if (typeof btoa === "function") {
    return btoa(value);
  }
  if (typeof Buffer !== "undefined") {
    return Buffer.from(value, "utf-8").toString("base64");
  }
  throw new Error("No base64 encoder available in this runtime.");
}

export class ModelApi {
  constructor(client, endpoint) {
    this.client = client;
    this.endpoint = endpoint;
  }

  list(query = undefined) {
    return this.client.request(this.endpoint, { method: "GET" }, query);
  }

  retrieve(id) {
    return this.client.request(`${this.endpoint}${id}/`, { method: "GET" });
  }

  create(payload) {
    return this.client.request(this.endpoint, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  update(id, payload) {
    return this.client.request(`${this.endpoint}${id}/`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  }

  partialUpdate(id, payload) {
    return this.client.request(`${this.endpoint}${id}/`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  }

  destroy(id) {
    return this.client.request(`${this.endpoint}${id}/`, { method: "DELETE" });
  }
}"""

    def render_model_section(self, model_definition: SdkModelDefinition) -> str:
        lines = [
            f"export const {model_definition.variable_name}Fields = {{",
            *[
                f"  {json.dumps(field.name)}: {json.dumps(self.serialize_field_metadata(field))},"
                for field in model_definition.fields
            ],
            "};",
            "",
            f"export class {model_definition.class_name}Api extends ModelApi {{",
            "  constructor(client) {",
            f'    super(client, "/api/{model_definition.endpoint_name}/");',
            "  }",
            "}",
        ]
        return "\n".join(lines)

    def render_sdk_class(self, model_definitions: list[SdkModelDefinition]) -> str:
        lines = [
            "export class BloomerpSdk {",
            "  constructor(config) {",
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
