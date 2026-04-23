# Bloomerp

## Getting Started

This section shows the recommended Bloomerp auth setup from first install onward.

The intended model is:

- install Bloomerp
- configure auth once in `BLOOMERP_CONFIG`
- let Bloomerp derive the auth engine details internally
- use one stable frontend contract for login, session, and social providers

### 1. Install Bloomerp

With `uv`:

```bash
uv add bloomerp
```

With `pip`:

```bash
pip install bloomerp
```

### 2. Add Bloomerp to Django settings

```python
from bloomerp.config import (
    BLOOMERP_APPS,
    BLOOMERP_AUTHENTICATION_BACKENDS,
    BLOOMERP_MIDDLEWARE,
    BLOOMERP_SITE_ID,
    BLOOMERP_USER_MODEL,
)
from bloomerp.config.definition import (
    BloomerpAuthSettings,
    BloomerpConfig,
    InteractiveAuthSettings,
    SessionAuthSettings,
    SocialProviderSettings,
)

INSTALLED_APPS += BLOOMERP_APPS
MIDDLEWARE += BLOOMERP_MIDDLEWARE

AUTH_USER_MODEL = BLOOMERP_USER_MODEL
AUTHENTICATION_BACKENDS = BLOOMERP_AUTHENTICATION_BACKENDS
SITE_ID = BLOOMERP_SITE_ID

BLOOMERP_CONFIG = BloomerpConfig(
    auto_generate_api_endpoints=True,
    auth=BloomerpAuthSettings(
        interactive=InteractiveAuthSettings(
            login_identifier="email",
            signup_enabled=True,
            password_reset_enabled=True,
            email_verification="optional",
            use_allauth=True,
            social_providers=[
                SocialProviderSettings(
                    provider="github",
                    client_id="env:BLOOMERP_GITHUB_CLIENT_ID",
                    client_secret="env:BLOOMERP_GITHUB_CLIENT_SECRET",
                ),
            ],
            allow_non_staff_bloomerp_access=False,
        ),
        session=SessionAuthSettings(
            enabled=True,
            login_identifier="email",
        ),
    ),
)
```

`LOGIN_URL` and `LOGOUT_URL` do not need to be set in a normal Bloomerp project. Bloomerp provides internal defaults and you only need to override them if you want custom auth paths.

### 3. Decide what kind of app you are building

Typical internal staff app:

- `allow_non_staff_bloomerp_access=False`
- `signup_enabled=False`

Typical backend platform with customer login:

- `allow_non_staff_bloomerp_access=False`
- `signup_enabled=True`

That second setup allows a user to authenticate, including with a social provider, without automatically granting access to Bloomerp’s internal staff pages.

### 4. Enable a social provider

Recommended mental model:

- provider behavior belongs in `BLOOMERP_CONFIG`
- provider secrets come from environment variables or a secret manager

Example:

```python
BLOOMERP_CONFIG = BloomerpConfig(
    auth=BloomerpAuthSettings(
        interactive=InteractiveAuthSettings(
            login_identifier="email",
            signup_enabled=True,
            email_verification="required",
            use_allauth=True,
            social_providers=[
                SocialProviderSettings(
                    provider="github",
                    client_id="env:BLOOMERP_GITHUB_CLIENT_ID",
                    client_secret="env:BLOOMERP_GITHUB_CLIENT_SECRET",
                    allow_login=True,
                    allow_signup=True,
                ),
            ],
            allow_non_staff_bloomerp_access=False,
        ),
        session=SessionAuthSettings(
            enabled=True,
            login_identifier="email",
        ),
    ),
)
```

And then provide secrets through environment variables, for example:

```bash
export GITHUB_CLIENT_ID="..."
export GITHUB_CLIENT_SECRET="..."
```

### 5. What Bloomerp should own

The recommended product direction is that Bloomerp is the only public auth configuration surface.

That means the app developer should not need to separately hand-configure `ACCOUNT_*`, `SOCIALACCOUNT_*`, URL mounts, or provider start/callback routes. Instead, Bloomerp should derive those internally from `BLOOMERP_CONFIG`.

In that model, declaring:

```python
InteractiveAuthSettings(
    use_allauth=True,
    social_providers=[
        SocialProviderSettings(provider="github"),
        SocialProviderSettings(provider="google"),
    ],
)
```

should be enough for Bloomerp to expose a stable auth contract such as:

- `GET /api/auth/session/`
- `GET /api/auth/csrf/`
- `POST /api/auth/login/`
- `POST /api/auth/logout/`
- `GET /api/auth/providers/`
- `GET /api/auth/providers/github/start/`
- `GET /api/auth/providers/google/start/`

The frontend can then:

1. fetch available providers from Bloomerp
2. render provider buttons dynamically
3. redirect the browser to the provider start URL
4. let Bloomerp complete OAuth and set the session
5. verify login through `/api/auth/session/`

### 6. Current state vs target state

Current state in Bloomerp:

- Bloomerp has a central auth config shape in `BLOOMERP_CONFIG.auth`
- browser login can already switch between username and email
- the registration API endpoint can already be enabled or disabled from config
- the login page can already render configured social providers
- `django-allauth` is treated as an optional engine when installed

Target state for frictionless provider support:

- provider metadata is declared in `BLOOMERP_CONFIG`
- Bloomerp auto-derives the internal `allauth` configuration
- Bloomerp auto-exposes provider start/callback endpoints
- the frontend only talks to Bloomerp auth endpoints, never directly to `allauth`

That target state is the recommended direction for Bloomerp if `django-allauth` becomes the standard interactive auth engine.

## Authentication

Bloomerp now treats authentication as two separate concerns:

- Interactive auth: browser-based login for human users
- API auth: SDK and machine access such as session auth, API keys, and bearer tokens

This split is intentional. Browser login and social login should be easy to configure without forcing the same implementation onto future SDK or machine-to-machine authentication.

## Current Direction

Interactive auth is configured through `BLOOMERP_CONFIG.auth.interactive`.

The goal is:

- keep Bloomerp as the public configuration surface
- allow instances to switch between username-based and email-based login
- support optional social login providers
- allow non-staff users to authenticate without automatically gaining access to the Bloomerp staff UI
- keep room for future API keys and token-based auth

## Example Configuration

```python
from bloomerp.config.definition import (
    BloomerpAuthSettings,
    BloomerpConfig,
    InteractiveAuthSettings,
    SessionAuthSettings,
    SocialProviderSettings,
)


BLOOMERP_CONFIG = BloomerpConfig(
    auto_generate_api_endpoints=True,
    auth=BloomerpAuthSettings(
        interactive=InteractiveAuthSettings(
            login_identifier="email",
            signup_enabled=True,
            password_reset_enabled=True,
            email_verification="required",
            use_allauth=True,
            social_providers=[
                SocialProviderSettings(provider="google"),
                SocialProviderSettings(provider="facebook"),
            ],
            allow_non_staff_bloomerp_access=False,
        ),
        session=SessionAuthSettings(
            enabled=True,
            login_identifier="email",
        ),
    ),
)
```

## Interactive Auth Settings

`InteractiveAuthSettings` currently supports:

- `enabled`: turns the interactive login flow on or off
- `login_identifier`: `"username"` or `"email"`
- `signup_enabled`: whether self-signup should be shown/enabled
- `password_reset_enabled`: whether reset-password UI should be shown
- `email_verification`: `"none"`, `"optional"`, or `"required"`
- `use_allauth`: enables `django-allauth` integration when installed
- `social_providers`: provider configs such as `SocialProviderSettings(provider="github")`
- `allow_non_staff_bloomerp_access`: whether authenticated non-staff users may access Bloomerp UI pages

## Staff UI vs Authenticated Users

Bloomerp distinguishes between:

- a user being authenticated
- a user being allowed to use the Bloomerp staff interface

This matters for product setups where Bloomerp is acting as a backend platform.

Example:

- a customer signs in with Google or Facebook
- that user is authenticated successfully
- but they should not automatically see Bloomerp’s internal staff pages

That behavior is controlled through:

- `allow_non_staff_bloomerp_access`
- `require_staff_for_access`

Recommended pattern for backend-style use cases:

- allow authentication for non-staff users
- keep Bloomerp UI access staff-only
- expose only the app-specific or API surfaces intended for those users

## django-allauth Integration

Bloomerp is prepared to use `django-allauth` for interactive auth, but only when both of the following are true:

1. `django-allauth` is installed
2. `use_allauth=True` in `InteractiveAuthSettings`

When enabled, Bloomerp can use `allauth` as the engine for:

- social login
- account flows
- email verification
- password reset

Bloomerp still keeps ownership of:

- the public configuration shape
- the branded login page
- the distinction between login and staff UI access

## Login UX

The Bloomerp login page remains Bloomerp-owned.

It now adapts to configuration by:

- showing `Email` or `Username` as the login field label
- updating login help text
- rendering configured social providers
- surfacing when social providers are configured but `allauth` is not yet available
- respecting password reset and email verification settings

## API Auth

Interactive auth does not replace Bloomerp’s API auth strategy.

API auth remains under `BLOOMERP_CONFIG.auth` and is the right place for future support such as:

- session auth for SDKs
- API keys
- bearer tokens
- custom authorization headers

This allows Bloomerp instances to support social login for end users while still exposing a separate, stable programmatic auth model.

## Recommended Product Pattern

For most deployed Bloomerp instances:

- keep one stable user model
- allow login by email or username through config
- use `django-allauth` for social login and account flows
- do not treat social-login users as staff by default
- keep machine auth separate from browser auth

This keeps authentication flexible without forcing every generated Bloomerp instance to invent its own auth architecture.
