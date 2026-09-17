from enum import Enum

from django.utils.translation import gettext_lazy as _

from bloomerp.dataviews.definition import DataviewTypeDefinition
from bloomerp.dataviews.calendar.config import CALENDAR_OPTIONS, CalendarDataView
from bloomerp.dataviews.calendar.renderer import CalendarDataviewRenderer
from bloomerp.dataviews.card.config import CARD_OPTIONS, CardDataView
from bloomerp.dataviews.card.renderer import CardDataviewRenderer
from bloomerp.dataviews.gant.config import GANTT_OPTIONS, GanttDataView
from bloomerp.dataviews.gant.renderer import GanttDataviewRenderer
from bloomerp.dataviews.kanban.config import KANBAN_OPTIONS, KanbanDataView
from bloomerp.dataviews.kanban.renderer import KanbanDataviewRenderer
from bloomerp.dataviews.pivot_table.config import (
    PIVOT_TABLE_OPTIONS,
    PivotTableDataView,
    PivotTableDataviewOptions,
)
from bloomerp.dataviews.pivot_table.renderer import PivotTableDataviewRenderer
from bloomerp.dataviews.table.config import TABLE_OPTIONS, TableDataView
from bloomerp.dataviews.table.renderer import TableDataviewRenderer
from bloomerp.utils.registry import BaseRegistry


class DataviewRegistry(BaseRegistry[DataviewTypeDefinition]):
    def register(self, key: str, obj: DataviewTypeDefinition) -> None:
        if any(definition.key == obj.key for definition in self.values()):
            raise ValueError(f"Dataview key {obj.key!r} is already registered")
        super().register(key, obj)

    def get(self, key: str) -> DataviewTypeDefinition | None:
        registered = super().get(key)
        if registered is not None:
            return registered
        return next(
            (definition for definition in self.values() if definition.key == key),
            None,
        )

    def choices(self) -> list[tuple[str, str]]:
        """Return model choices from the currently registered dataviews."""
        return [(definition.key, definition.label) for definition in self.values()]


def get_dataview_type_choices() -> list[tuple[str, str]]:
    """Resolve dataview choices when Django evaluates the model field."""
    return DATAVIEW_REGISTRY.choices()

DATAVIEW_REGISTRY = DataviewRegistry(
    registry_item_class=DataviewTypeDefinition
)

DATAVIEW_REGISTRY.register(
    "table",
    DataviewTypeDefinition(
        key="table",
        label=_("Table"),
        description=_("Displays records in a sortable table."),
        icon="fa fa-table",
        renderer_cls=TableDataviewRenderer,
        config_cls=TableDataView,
        opts=TABLE_OPTIONS,
    )
)

DATAVIEW_REGISTRY.register(
    "kanban",
    DataviewTypeDefinition(
        key="kanban",
        label=_("Kanban"),
        description=_("Displays records in a kanban board."),
        icon="fa fa-columns",
        renderer_cls=KanbanDataviewRenderer,
        config_cls=KanbanDataView,
        opts=KANBAN_OPTIONS,
    )
)

DATAVIEW_REGISTRY.register(
    "card",
    DataviewTypeDefinition(
        key="card",
        label=_("Card"),
        description=_("Displays records in a card grid."),
        icon="fa fa-id-card",
        renderer_cls=CardDataviewRenderer,
        config_cls=CardDataView,
        opts=CARD_OPTIONS,
    )
)

DATAVIEW_REGISTRY.register(
    "calendar",
    DataviewTypeDefinition(
        key="calendar",
        label=_("Calendar"),
        description=_("Displays records in a calendar view."),
        icon="fa fa-calendar",
        renderer_cls=CalendarDataviewRenderer,
        config_cls=CalendarDataView,
        opts=CALENDAR_OPTIONS,
    )
)

DATAVIEW_REGISTRY.register(
    "gantt",
    DataviewTypeDefinition(
        key="gantt",
        label=_("Gantt"),
        description=_("Displays records in a Gantt chart."),
        icon="fa fa-chart-gantt",
        renderer_cls=GanttDataviewRenderer,
        config_cls=GanttDataView,
        opts=GANTT_OPTIONS,
    )
)

DATAVIEW_REGISTRY.register(
    "pivot_table",
    DataviewTypeDefinition(
        key="pivot_table",
        label=_("Pivot"),
        description=_("Displays records in a pivot table."),
        icon="fa fa-table",
        renderer_cls=PivotTableDataviewRenderer,
        config_cls=PivotTableDataView,
        opts=PIVOT_TABLE_OPTIONS,
    )
)


