# Bloomerp TypeScript SDK

Generated SDK entry file: `sdk.ts`

## Setup

```ts
import BloomerpSdk from "./sdk.ts";

const sdk = new BloomerpSdk({
  baseUrl: "https://example.com",
  auth: {
    type: "session",
    credentials: "include",
  },
});
```

## Session Auth

```ts
await sdk.auth.csrf();
await sdk.auth.login({
  username: "admin",
  password: "password",
});

const session = await sdk.auth.session();
```

## Read One

```ts
const item = await sdk.aiConversations.retrieve("1");
```

## Create

```ts
const created = await sdk.aiConversations.create({
  // fill in required fields here
}, {
  headers: {
    "X-Request-Source": "web",
  },
});
```

## Filter / List

```ts
const page = await sdk.aiConversations.list({
  args: "Example",
}, {
  cache: "no-store",
});

const results = page.results;
```

## Inspect Field Options

```ts
const statusChoices = sdk.metadata.models.todos?.fields.status.choices ?? [];

for (const option of statusChoices) {
  console.log(option.value, option.label);
}
```

## Handle Validation Errors

```ts
import BloomerpSdk, { BloomerpHttpError } from "./sdk.ts";

const sdk = new BloomerpSdk({
  baseUrl: "https://example.com",
});

try {
  await sdk.aiConversations.create({
    // invalid payload
  });
} catch (error) {
  if (error instanceof BloomerpHttpError && error.status === 400) {
    const fieldErrors = error.body as Record<string, string[]>;
    console.log(fieldErrors);
  } else {
    throw error;
  }
}
```

## Notes

- `sdk.auth.*` targets Bloomerp's built-in `/api/auth/*` endpoints.
- `list()` always returns a paginated shape with `results`, `count`, `next`, and `previous`.
- Per-request options flow through to `fetch`, including `cache`, `credentials`, `headers`, `signal`, and framework-specific fetch options.
- Structured failures throw `BloomerpHttpError`.
- Choice fields expose `{ value, label }` metadata under `sdk.metadata.models.<model>.fields.<field>.choices`.
- Example model shown above: `AIConversation`.
