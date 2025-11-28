from registries.route_registry import router
from django.http import HttpResponse
from django.http import HttpRequest
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404, render


@router.register(
    path="components/create-object/<int:content_type_id>/",
    name="components_create_object",
)
def create_object(request: HttpRequest, content_type_id: int) -> HttpResponse:
    """Renders the create object form for the given content type ID.

    Args:
        request (HttpRequest): The request object.
        content_type_id (int): The content type ID of the object to create.

    Returns:
        HttpResponse: The rendered create object form.
    """
    content_type = get_object_or_404(ContentType, id=content_type_id)
    model_class = content_type.model_class()
    
    # TODO: 1. Check permissions (user needs crud permission)
    # 2. Render the form -> has to be scalable bcs of usage in View
    # 3. Handle form submission (POST request)
    # 4. Return appropriate response (success or error)
    # 5. Make sure to include a button somewhere to go to the actual view (this is a component)
    
    
    return HttpResponse("<p>Hello World</p>")