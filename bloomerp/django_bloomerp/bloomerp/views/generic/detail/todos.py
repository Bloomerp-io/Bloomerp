from bloomerp.filters.definition import Filter, FilterCondition, Filters
from bloomerp.models.project_management.initiative import Initiative
from bloomerp.models.project_management.todo import Todo
from bloomerp.router import router
from bloomerp.views.generic.detail.base import BaseBloomerpDetailView
from bloomerp.views.mixins.dataview_mixin import DataviewMixin
from django.contrib.contenttypes.models import ContentType

@router.register(
    path="todos/",
    route_type="detail",
    name="Todos",
    description="Todos related to a specific object",
    exclude_models=[Todo, Initiative],
    url_name="todos"
)
class ObjectTodosView(DataviewMixin, BaseBloomerpDetailView):
    """
    A generic view for displaying todos related to a specific object.
    """

    model = None  # This will be set dynamically based on the registered model
    args = {"hide_filters": "object_id,content_type"}
    dataview_filter_shorthand = True

    def get_dataview_content_type_id(self) -> int:
        """Render Todo records in this object's tab."""
        return ContentType.objects.get_for_model(Todo).pk

    def get_dataview_filters(self) -> Filters:
        """Filter to-dos by both identifiers of the current record."""
        return [Filter(connector="AND", conditions=[
            FilterCondition(field_path="object_id", lookup_id="equals", value=str(self.object.pk)),
            FilterCondition(
                field_path="content_type",
                lookup_id="equals",
                value=ContentType.objects.get_for_model(self.object).pk,
            ),
        ])]
    
