from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from bloomerp.models.application_field import ApplicationField
from django.contrib.contenttypes.models import ContentType
from bloomerp.router import router
from bloomerp.field_types import FieldType

FILTERABLE_FIELD_TYPES = [
    field_type.value.id for field_type in FieldType if field_type.value.allow_in_model
]


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
        application_fields = ApplicationField.get_for_content_type_id(content_type_id).filter(
            field_type__in=FILTERABLE_FIELD_TYPES
        )
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
        field_path = request.GET.get("field_path", None)
        base_application_field_id = request.GET.get("base_application_field_id", None)
        
        # Get the field type
        field_type = application_field.get_field_type_enum()
        
        return render(
            request,
            "components/application_fields/lookup_operators.html",
            {
                "application_field": application_field,
                "lookups": field_type.lookups,
                "field_path": field_path,
                "base_application_field_id": base_application_field_id,
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
        field_path = request.GET.get("field_path", None)
        
        field_type = application_field.get_field_type_enum()
        
        # Get the lookup value
        lookup_option = None
        for option in field_type.lookups:
            if option.value.id == lookup_value:
                lookup_option = option
                break
        
        if not lookup_option:
            return HttpResponse("Invalid lookup operator.", status=400)
        
        # Special handling for advanced foreign key lookups
        if lookup_value == "foreign_advanced":
            related_model = application_field.get_related_model()
            if not related_model:
                return HttpResponse("Related model not found.", status=400)
            related_content_type_id = ContentType.objects.get_for_model(related_model).id
            related_fields = ApplicationField.get_for_content_type_id(related_content_type_id).filter(
                field_type__in=FILTERABLE_FIELD_TYPES
            )

            return render(
                request,
                "components/filters/advanced_lookup.html",
                {
                    "base_field": application_field,
                    "related_fields": related_fields,
                    "related_content_type_id": related_content_type_id,
                }
            )
        
        lookup = application_field.get_field_type_enum().get_lookup_by_id(lookup_value).value
        
        return HttpResponse(lookup.render(application_field, name_override=field_path))
        
    except ApplicationField.DoesNotExist:
        return HttpResponse("Application field not found.", status=404)


@router.register(
    path='components/filters/<int:content_type_id>/related-fields/',
    name='components_filters_related_fields'
)
def related_fields(
    request: HttpRequest,
    content_type_id: int,
) -> HttpResponse:
    """Returns a select list of related fields for advanced filter chaining."""
    try:
        level = int(request.GET.get("level", 1))
    except (TypeError, ValueError):
        level = 1

    path_prefix = request.GET.get("path_prefix", "")

    application_fields = ApplicationField.get_for_content_type_id(content_type_id).filter(
        field_type__in=FILTERABLE_FIELD_TYPES
    )

    expandable_field_types = {
        FieldType.FOREIGN_KEY.id,
        FieldType.MANY_TO_MANY_FIELD.id,
        FieldType.ONE_TO_ONE_FIELD.id,
    }

    return render(
        request,
        "components/filters/related_fields_select.html",
        {
            "application_fields": application_fields,
            "level": level,
            "path_prefix": path_prefix,
            "expandable_field_types": expandable_field_types,
        }
    )
    
    
