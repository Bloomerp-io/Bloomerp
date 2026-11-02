"""Check consistent core server selection for templates and app imports."""

from types import SimpleNamespace

import pytest
from django.http import HttpRequest
from django.test import override_settings

from bloomerp.context_processors import debug_mode
from bloomerp.frontend.settings import get_core_vite_dev_server_url


@pytest.mark.parametrize("explicit", [None, "", "http://localhost:7000/"])
def test_explicit_core_server_overrides_config(explicit: str | None) -> None:
    """Allow disabling core's server without disabling an app's Vite server."""
    with override_settings(
        BLOOMERP_CONFIG=SimpleNamespace(vite_dev_server_url="http://localhost:5173"),
        BLOOMERP_VITE_DEV_SERVER_URL=explicit,
    ):
        expected = (explicit or "").rstrip("/")
        assert get_core_vite_dev_server_url() == expected
        assert debug_mode(HttpRequest())["BLOOMERP_VITE_DEV_SERVER_URL"] == expected


def test_core_config_remains_the_default() -> None:
    """Preserve the existing framework configuration when no override is declared."""
    from django.conf import settings

    with override_settings(
        BLOOMERP_CONFIG=SimpleNamespace(vite_dev_server_url="http://localhost:5173/")
    ):
        if hasattr(settings, "BLOOMERP_VITE_DEV_SERVER_URL"):
            del settings.BLOOMERP_VITE_DEV_SERVER_URL
        assert get_core_vite_dev_server_url() == "http://localhost:5173"
