from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from bloomerp.models.application_field import ApplicationField
from registries.route_registry import router


@router.register(
    path='components/permissions-table/',
    name='components_permissions_table'
)
def permissions_table(request:HttpRequest):
    # Some logic here
    
    return render(
        request,
        "components/permissions_table.html"
    )


@router.register(
    path='components/row-policy/<int:application_field_id>/value/',
    name='components_row_policy'
)
def row_policy(
    request:HttpRequest,
    application_field_id:int,
    ) -> HttpResponse:
    lookup = request.GET.get("lookup", "equals")
    selected_lookup = None
    
    # Get the application field
    application_field = ApplicationField.objects.get(id=application_field_id)
    
    # Get the field type
    field_type = application_field.get_field_type_enum()
    
    # Get the lookups
    for lk in field_type.lookups:
        if lk.value.django_representation == lookup:
            selected_lookup = lk.value
            break
    
    
    return HttpResponse(f"Value input for {application_field.field} with lookup {selected_lookup.django_representation}")
    
