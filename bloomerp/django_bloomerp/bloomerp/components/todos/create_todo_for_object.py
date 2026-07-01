from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse

from bloomerp.components.objects.crud_object import CreateObjectComponentView
from bloomerp.models.project_management.todo import Todo
from bloomerp.router import router
from bloomerp.utils.models import get_detail_base_view_url


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
    query_params["next"] = reverse(get_detail_base_view_url(ContentType.objects.get_for_id(content_type_id).model_class()) + "_todos", kwargs={"pk": object_id})
    request.GET = query_params
    
    return CreateObjectComponentView.as_view()(
        request,
        content_type_id=todo_content_type.pk,
    )
