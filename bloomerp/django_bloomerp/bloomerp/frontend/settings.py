"""Resolve the core frontend server consistently for templates and extensions."""

from django.conf import settings


def get_core_vite_dev_server_url() -> str:
    """Return the explicit Django override or core config URL, with empty values disabling it."""
    configured = getattr(
        getattr(settings, "BLOOMERP_CONFIG", None),
        "vite_dev_server_url",
        "http://localhost:5173",
    )
    return (getattr(settings, "BLOOMERP_VITE_DEV_SERVER_URL", configured) or "").rstrip(
        "/"
    )
