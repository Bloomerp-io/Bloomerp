# Authentication

Configure browser login under `BLOOMERP_CONFIG.auth.interactive` and programmatic
access under `BLOOMERP_CONFIG.auth`. Authentication establishes the caller;
model, row, and field permissions still determine what that caller may access.

## Browser and session login

In a generated project, add overrides to `config/settings/common.py`. Adapt your
existing `BloomerpConfig` rather than discarding its other settings:

```python
from bloomerp.config.definition import (
    BloomerpAuthSettings,
    BloomerpConfig,
    InteractiveAuthSettings,
    SessionAuthSettings,
)


BLOOMERP_CONFIG = BloomerpConfig(
    auth=BloomerpAuthSettings(
        interactive=InteractiveAuthSettings(
            login_identifier="email",
            signup_enabled=False,
            allow_non_staff_bloomerp_access=False,
        ),
        session=SessionAuthSettings(enabled=True, login_identifier="email"),
    ),
)
```

Both identifiers default to `username`. Keep them aligned when the browser UI
and API should accept the same credentials. Enabling signup does not make new
users staff or grant access to internal pages. Staff-page access also depends
on `BloomerpConfig.require_staff_for_access` and the route's access checks.

The session API exposes:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/auth/csrf/` | Obtain a CSRF token. |
| GET | `/api/auth/session/` | Inspect the current session. |
| POST | `/api/auth/login/` | Authenticate with the configured identifier and password. |
| POST | `/api/auth/logout/` | End the session. |
| POST | `/api/auth/register/` | Register when signup is enabled. |

Browser clients retain cookies and send the CSRF token with state-changing
session requests.

## Social login

Social login requires `django-allauth`, `use_allauth=True`, and configured
`SocialProviderSettings` entries. Provider credentials can use environment
references such as `client_id="env:BLOOMERP_GITHUB_CLIENT_ID"` and
`client_secret="env:BLOOMERP_GITHUB_CLIENT_SECRET"`.

The project must include the allauth apps, middleware, authentication backend,
and the selected provider app in its Django settings. Bloomerp exports the
common settings through `bloomerp.config`; provider apps follow
`allauth.socialaccount.providers.<provider>`. Bloomerp derives account defaults
and `SOCIALACCOUNT_PROVIDERS` from the configuration during startup and mounts
allauth under `/accounts/` when enabled.

Use the provider links rendered by Bloomerp's login page. There is no
`/api/auth/providers/` discovery endpoint or Bloomerp-specific provider-start
API. Configure the provider's callback against the mounted allauth routes.

`email_verification` accepts `none`, `optional`, or `required`.
`password_reset_enabled` controls the reset-password UI. Configure the instance's
email delivery for account emails.

## API keys and MCP

Enable `ApiKeyAuthSettings(enabled=True)` under `BloomerpAuthSettings.api_key`
to accept instance-issued API keys. Send a key as `Authorization: Bearer <key>`
or through the configured header (`X-API-Key` by default). Keys act as their
associated account and retain its permissions.

Generated REST APIs also use DRF session and Basic authentication. OAuth for
[MCP](mcp/index.md) is a separate, resource-scoped transport; an MCP OAuth token
does not automatically authenticate ordinary REST endpoints.
