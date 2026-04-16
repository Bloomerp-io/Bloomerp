from typing import Literal, Optional

from pydantic import BaseModel, Field


class SessionAuthSettings(BaseModel):
    enabled: bool = True
    login_identifier: Literal["username", "email", "custom"] = "username"
    custom_identifier_field: str | None = None
    user_fields: list[str] = Field(
        default_factory=lambda: ["id", "username", "email", "first_name", "last_name"]
    )

    def get_identifier_field_name(self) -> str:
        if self.login_identifier == "custom":
            return str(self.custom_identifier_field or "identifier")
        return self.login_identifier


class BearerAuthSettings(BaseModel):
    enabled: bool = False


class ApiKeyAuthSettings(BaseModel):
    enabled: bool = False
    header_name: str = "X-API-Key"


class AuthorizationAuthSettings(BaseModel):
    enabled: bool = False


class CustomAuthSettings(BaseModel):
    enabled: bool = False
    name: str = "custom"


class BloomerpAuthSettings(BaseModel):
    session: SessionAuthSettings = Field(default_factory=SessionAuthSettings)
    bearer: BearerAuthSettings = Field(default_factory=BearerAuthSettings)
    api_key: ApiKeyAuthSettings = Field(default_factory=ApiKeyAuthSettings)
    authorization: AuthorizationAuthSettings = Field(default_factory=AuthorizationAuthSettings)
    custom: CustomAuthSettings = Field(default_factory=CustomAuthSettings)

    def enabled_strategy_types(self) -> list[str]:
        strategies: list[tuple[str, bool]] = [
            ("session", self.session.enabled),
            ("bearer", self.bearer.enabled),
            ("apiKey", self.api_key.enabled),
            ("authorization", self.authorization.enabled),
            ("custom", self.custom.enabled),
        ]
        return [strategy_type for strategy_type, enabled in strategies if enabled]

    def is_strategy_enabled(self, strategy_type: str) -> bool:
        return strategy_type in self.enabled_strategy_types()

class BloomerpConfig(BaseModel):
    """
    Configuration class to be set on the settings. This contains all the necessary configurable settings for bloomerp.

    Settings are:
    - **auto_generate_api_endpoints** : whether to automatically generate API endpoints for all models. If True, API endpoints will be generated for all models in the application. If False, no API endpoints will be generated. If None, API endpoints will be generated for all models that do not have a custom API endpoint defined. Note that this can be overridden on a per model basis by setting the `auto_generate_api_endpoint` attribute on the model's configuration.
    - **vite_dev_server_url**: the URL of the Vite development server. This is used for hot module replacement (HMR) during development. The default value is 'http://localhost:5173'. This setting is only used if BLOOMERP_VITE_DEV_SERVER_URL is not set in the settings.

    Usage (in settings.py)
    ```python
    from bloomerp.config.definition import BloomerpConfig

    bloomerp_config = BloomerpConfig(
        ...
    )
    ```
    """

    auto_generate_api_endpoints : bool = True

    vite_dev_server_url : Optional[str] = 'http://localhost:5173'

    auth: BloomerpAuthSettings = Field(default_factory=BloomerpAuthSettings)
    


