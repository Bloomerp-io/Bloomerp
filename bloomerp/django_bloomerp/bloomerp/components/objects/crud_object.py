from bloomerp.forms.model_form import bloomerp_modelform_factory
from bloomerp.router import router
from django.http import HttpResponse
from django.http import HttpRequest
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from django.forms.models import modelform_factory
from bloomerp.forms.core import BloomerpModelForm
from bloomerp.utils.requests import render_blank_form

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
    ModelForm = modelform_factory(
        model_class,
        form=BloomerpModelForm,
        fields="__all__",
    )

    form = ModelForm(
        model=model_class,
        user=request.user,
    )
    
    return render_blank_form(
            request, 
            form, 
            {}, 
            f"/components/create-object/{content_type_id}/"
        )


@router.register(
    path="components/delete-object/<int:content_type_id>/<str:object_id>/",
    name="components_delete_object",
)
def delete_object(request:HttpRequest, content_type_id:int, object_id:str|int) -> HttpResponse:
    """Returns the delete object component

    Args:
        request (HttpRequest): the request object
        content_type_id (int): the content type ID
        object_id (str|int): the object ID

    Returns:
        HttpResponse: the response object
    """
    if request.method == "GET":
        pass
        # Return a are you sure you want to delete text
        # incl. 
    if request.method == "DELETE":
        pass 
        # Delete the object if the user can delete objects
        
        
@router.register(
    path="components/update-object/<int:content_type_id>/<str:object_id>/",
    name="components_update_object",
)
def update_object(request:HttpRequest, content_type_id:int, object_id:str|int) -> HttpResponse:
    """Returns the delete object component

    Args:
        request (HttpRequest): the request object
        content_type_id (int): the content type ID
        object_id (str|int): the object ID

    Returns:
        HttpResponse: the response object
    """
    # TODO : Integrate permissions using permissions services
    content_type = ContentType.objects.get(id=content_type_id)
    ModelCls = content_type.model_class()
    object = get_object_or_404(ModelCls, id=object_id)
    FormCls = bloomerp_modelform_factory(ModelCls, "__all__")
    
    if request.method == "GET":    
    
        return render_blank_form(
            request,
            FormCls(instance=object),
            {},
            ""
        )
    elif request.method == "POST":
        form = FormCls(instance=object, data=request.POST, files=request.FILES)