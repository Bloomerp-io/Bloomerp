from urllib.parse import urlsplit

from django.urls import Resolver404, resolve


def supports_main_content_navigation(url: str) -> bool:
    """Identify local destinations that support the main-content HTMX fragment."""
    from bloomerp.views.mixins.htmx_mixin import HtmxMixin

    try:
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
            return False
        view_class = getattr(resolve(parsed.path).func, "view_class", None)
    except (Resolver404, ValueError):
        return False

    return (
        isinstance(view_class, type)
        and issubclass(view_class, HtmxMixin)
        and view_class.htmx_main_target == "main-content"
        and view_class.htmx_include_addendum
    )
