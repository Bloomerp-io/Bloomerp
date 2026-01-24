import select
from attr import field
import django
import django.forms
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from bloomerp.field_types import FieldType, Lookup
from bloomerp.models.application_field import ApplicationField
from bloomerp.utils.form_fields import render_single_field
from registries.route_registry import router

@router.register(
    path='components/filters/<int:content_type_id>/init/',
    name='components_filters_init'
)
def filters_init(request:HttpRequest, content_type_id:int) -> HttpResponse:
    """
    Initializes the filter component for a given content type.
    """
    application_field_id = request.GET.get("application_field_id", None)
    selected_application_field = None
    html_content = ""
    
    # TODO: integrate with permissions
    if not application_field_id:
        application_fields = ApplicationField.get_for_content_type_id(content_type_id)
    else:
        application_fields = None
        selected_application_field = ApplicationField.objects.get(id=application_field_id)
        
        # In this case, go to step 2 already
        html_content = filters_lookup_operators(
            request,
            content_type_id,
            application_field_id
        ).content.decode("utf-8")

    return render(
        request,
        "components/filters/init.html",
        {
            "content_type_id": content_type_id,
            "application_fields": application_fields,
            "selected_application_field": selected_application_field,
            "html_content": html_content,
        }    
    )


@router.register(
    path='components/filters/<int:content_type_id>/lookup-operators/<int:application_field_id>/',
    name='components_filters_lookup_operators'
)
def filters_lookup_operators(
    request:HttpRequest,
    content_type_id:int,
    application_field_id:int
    ) -> HttpResponse:
    """Returns a select field containing all of the lookup operators for a certain application field. 

    Args:
        request (HttpRequest): the request object
        content_type_id (int): the content type id
        application_field_id (int): the application field id    
    Returns:
        HttpResponse: the response object
    """
    try:
        # Get the application field
        application_field = ApplicationField.objects.get(id=application_field_id)
        
        # Get the field type
        field_type = application_field.get_field_type_enum()
        
        return render(
            request,
            "components/application_fields/lookup_operators.html",
            {
                "application_field": application_field,
                "lookups": field_type.lookups,
            }
        )
    except ApplicationField.DoesNotExist:
        return HttpResponse("Application field not found.", status=404)
    
    
@router.register(
    path='components/filters/<int:content_type_id>/value-input/<int:application_field_id>/',
    name='components_filters_value_input'
)
def value_input(
    request:HttpRequest, 
    content_type_id:int, 
    application_field_id:int) -> HttpResponse:
    """Returns a value input field for a certain application field. 

    Args:
        request (HttpRequest): the request object
        content_type_id (int): the content type id
        application_field_id (int): the application field id
    GET Parameters:
        lookup_value (str): the selected lookup operator value
    Returns:
        HttpResponse: the response object
    """
    try:
        # Get the selected application field and operator
        lookup_value = request.GET.get("lookup_value", "")
        application_field = ApplicationField.objects.get(id=application_field_id)
        
        field_type = application_field.get_field_type_enum()
        
        
        # Get the lookup value
        lookup_option = None
        for option in field_type.lookups:
            if option.value.id == lookup_value:
                lookup_option = option
                break
        
        if not lookup_option:
            return HttpResponse("Invalid lookup operator.", status=400)
        
        lookup = application_field.get_field_type_enum().get_lookup_by_id(lookup_value).value
        
        return HttpResponse(lookup.render(application_field))
        
    except ApplicationField.DoesNotExist:
        return HttpResponse("Application field not found.", status=404)
    
    