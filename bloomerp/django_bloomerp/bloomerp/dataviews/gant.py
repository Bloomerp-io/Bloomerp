from __future__ import annotations

from .base import BaseDataviewRenderer


class GantDataviewRenderer(BaseDataviewRenderer):
    template_name = "cotton/features/dataviews/gant.html"
