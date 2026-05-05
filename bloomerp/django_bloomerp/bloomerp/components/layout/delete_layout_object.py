import re

from django.http import HttpRequest, HttpResponse
from django.urls import reverse

from bloomerp.router import router
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404

from bloomerp.utils.requests import render_blank_form

@router.register(
    path="components/layout/available-object/<int:content_type_id>/<str:object_id>",
    name="components_delete_layout_object"
)
def delete_layout_object(request:HttpRequest, content_type_id: int, object_id: str) -> HttpResponse:
    """Endpoint to delete a layout object

    Args:
        request (HttpRequest): the request object
        content_type_id (int): content type id
        object_id (str): object id
    """
    object = get_object_or_404(
        ContentType.objects.get(id=content_type_id).model_class(),
        pk=object_id,
    )
    
    match request.method:
        case "POST":
            object.delete()
            return HttpResponse(status=204)
        case "GET":
            return render_blank_form(
                request,
                form=None,
                url=reverse("components_delete_layout_object", args=[content_type_id, object_id]),
                submit_label="Confirm Delete",
                button_attrs={
                    "bloomerp-close-modal" : "layout-object-delete-modal" 
                },
                text="Are you sure you want to delete this layout item? This action cannot be undone.",
            )
            


