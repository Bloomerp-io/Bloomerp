from __future__ import annotations

from .base import BaseDataviewRenderer


class PivotTableDataviewRenderer(BaseDataviewRenderer):
    template_name = "cotton/features/dataviews/pivot_table.html"
