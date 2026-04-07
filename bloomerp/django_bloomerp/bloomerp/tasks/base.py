

from importlib.util import find_spec

from django.conf import settings


def _has_configured_celery_broker() -> bool:
    """Return whether Django settings expose a usable Celery broker URL.

    Returns:
        bool: True when ``CELERY_BROKER_URL`` is configured with a non-empty value.
    """
    broker_url = getattr(settings, "CELERY_BROKER_URL", None)
    if broker_url is None:
        return False

    broker_url = str(broker_url).strip()
    return broker_url != ""


def is_celery_available() -> bool:
    """Return whether Celery appears usable in the current Django environment.

    The check intentionally stays lightweight: it verifies that the Celery package
    can be imported and that Django settings include the minimum broker setting
    needed to dispatch a task. It does not prove that a worker is running or that
    the broker is currently reachable.

    Returns:
        bool: True when Celery is installed and Django settings define a usable
        ``CELERY_BROKER_URL``.
    """
    return find_spec("celery") is not None and _has_configured_celery_broker()