"""Template integration for installed frontend extensions."""

import json
from typing import Any

from django import template
from django.utils.safestring import SafeString, mark_safe

from bloomerp.frontend.assets import get_frontend_assets

register = template.Library()


@register.simple_tag
def frontend_assets() -> dict[str, Any]:
    """Resolve installed frontend bundles for the page's initial shell."""
    return get_frontend_assets()


@register.simple_tag
def frontend_importmap(imports: dict[str, str]) -> SafeString:
    """Render an import map with script-breaking HTML characters escaped."""
    data = json.dumps({"imports": imports}).translate(
        {ord("<"): "\\u003C", ord(">"): "\\u003E", ord("&"): "\\u0026"}
    )
    return mark_safe(f'<script type="importmap">{data}</script>')
