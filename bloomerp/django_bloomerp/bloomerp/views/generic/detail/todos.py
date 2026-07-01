from bloomerp.models.project_management.initiative import Initiative
from bloomerp.models.project_management.todo import Todo
from bloomerp.router import router
from bloomerp.views.generic.detail.base import BaseBloomerpDetailView
from django.contrib.contenttypes.models import ContentType

@router.register(
    path="todos/",
    route_type="detail",
    name="Todos",
    description="Todos related to a specific object",
    exclude_models=[Todo, Initiative]
)
class ObjectTodosView(BaseBloomerpDetailView):
    """
    A generic view for displaying todos related to a specific object.
    """

    model = None  # This will be set dynamically based on the registered model
    template_name = "views/generic/detail/todos.html"
    
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["todo_content_type_id"] = ContentType.objects.get_for_model(Todo).id
        ctx["filters"] = {
            "object_id": self.object.pk,
            "content_type_id": ContentType.objects.get_for_model(self.object).id
        }
        ctx["args"] = {
            "hide-filters" : "object_id,content_type_id"
        }
        
        return ctx
    
