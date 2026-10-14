import json

from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from bloomerp.components.objects.crud.create_update import CreateObjectComponentView
from bloomerp.forms.model_form import BloomerpModelForm
from bloomerp.models.project_management.todo import Todo
from bloomerp.router import router


class _CreateTodoForObjectView(CreateObjectComponentView):
    """Keep object-linked todo creation inside its dialog until the save succeeds."""

    def form_valid(self, form: BloomerpModelForm) -> HttpResponse:
        """Close the todo dialog after saving and deliver the queued success feedback."""
        response = super().form_valid(form)
        if not self.request.htmx or form.errors:
            return response
        response = render(self.request, "components/todos/create_todo_success.html")
        response["HX-Trigger"] = json.dumps({
            "bloomerp:close-modal": {"modalId": "detail-todo-modal"},
        })
        return response


@router.register(
    path="components/todo/create-todo-for-object/<int:content_type_id>/<str:object_id>/",
    name="components_create_todo_for_object",
)
def create_todo_for_object(
    request: HttpRequest,
    content_type_id: int,
    object_id: str,
) -> HttpResponse:
    """Returns the create todo component for an object

    Args:
        request (HttpRequest): the request object
        content_type_id (int): the content type ID of the object
        object_id (str): the object ID
    Returns:
        HttpResponse: the response object
    """
    get_object_or_404(ContentType, id=content_type_id)
    todo_content_type = ContentType.objects.get_for_model(Todo)

    query_params = request.GET.copy()
    query_params["content_type_id"] = str(content_type_id)
    query_params["content_type"] = str(content_type_id)
    query_params["object_id"] = str(object_id)
    request.GET = query_params
    
    return _CreateTodoForObjectView.as_view()(
        request,
        content_type_id=todo_content_type.pk,
    )
