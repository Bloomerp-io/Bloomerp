from __future__ import annotations

from .base import BaseDataviewRenderer


class PivotTableDataviewRenderer(BaseDataviewRenderer):
    template_name = "cotton/ui/data_view/pivot_table.html"
