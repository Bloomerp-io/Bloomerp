from __future__ import annotations

from django.conf import settings
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from bloomerp.config.definition import BloomerpConfig
from bloomerp.models.api_key import ApiKey


def get_bloomerp_config() -> BloomerpConfig:
    config = getattr(settings, "BLOOMERP_CONFIG", None)
    if isinstance(config, BloomerpConfig):
        return config
    return BloomerpConfig()


class BloomerpApiKeyAuthentication(BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        if not self._is_enabled():
            return None

        raw_token = self._get_token(request)
        if not raw_token:
            return None

        key_prefix = ApiKey.extract_key_prefix(raw_token)
        if not key_prefix:
            raise AuthenticationFailed("Invalid API key.")

        api_key = (
            ApiKey.objects
            .select_related("account")
            .filter(key_prefix=key_prefix)
            .first()
        )
        if api_key is None or not api_key.check_token(raw_token):
            raise AuthenticationFailed("Invalid API key.")

        api_key.mark_used()
        return (api_key.account, api_key)

    def authenticate_header(self, request):
        return self.keyword

    def _is_enabled(self) -> bool:
        return bool(get_bloomerp_config().auth.api_key.enabled)

    def _get_token(self, request) -> str:
        token = self._get_bearer_token(request)
        if token:
            return token

        header_name = get_bloomerp_config().auth.api_key.header_name
        return str(request.headers.get(header_name, "")).strip()

    def _get_bearer_token(self, request) -> str:
        auth = get_authorization_header(request).split()
        if not auth:
            return ""

        keyword = auth[0].decode("utf-8", errors="ignore")
        if keyword.lower() != self.keyword.lower():
            return ""

        if len(auth) != 2:
            raise AuthenticationFailed("Invalid Authorization header.")

        return auth[1].decode("utf-8", errors="ignore").strip()
