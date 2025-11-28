from django.shortcuts import get_object_or_404, render
from registries.route_registry import router
from django.http import HttpResponse
from django.http import HttpRequest
from django.contrib.contenttypes.models import ContentType
from bloomerp.services.permission_services import get_queryset_for_user
from bloomerp.services.user_services import get_data_view_fields
from bloomerp.services.user_services import get_accessible_fields_for_user
from bloomerp.services.user_services import get_user_list_view_preference
from bloomerp.services.user_services import toggle_field_visibility
from bloomerp.services.object_services import string_search_on_queryset
from bloomerp.utils.filters import filter_model
from bloomerp.models.user_list_view_preference import UserListViewPreference
from bloomerp.models.user_list_view_preference import ViewType
from bloomerp.models.user_list_view_preference import PageType
from bloomerp.models.user_list_view_preference import PageSize
from bloomerp.models import ApplicationField
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from collections import defaultdict
from django.db.models import QuerySet


# -----------------------------------
# Helper functions for different view types
# -----------------------------------
def _get_extra_context_for_view_type(preference:UserListViewPreference, queryset:QuerySet) -> dict:
    """Returns the extra context for a particular view type.

    Args:
        view_type (ViewType): the view type

    Returns:
        dict: _description_
    """
    context = {}
    
    match preference.view_type:
        case ViewType.TABLE:
            pass
        case ViewType.KANBAN:
            kanban_groups = None
            kanban_group_by_field = None
            if preference.view_type == ViewType.KANBAN and preference.kanban_group_by_field:
                kanban_group_by_field = preference.kanban_group_by_field
                kanban_groups = _build_kanban_groups(queryset, kanban_group_by_field)
            
            context["kanban_groups"] = kanban_groups
            context["kanban_group_by_field"] = kanban_group_by_field
            
        case ViewType.CALENDAR:
            pass
        case _:
            pass
    
    return context
    
def _build_kanban_groups(queryset, group_by_field: ApplicationField) -> list:
    """
    Builds kanban groups from a queryset based on a grouping field.
    
    Args:
        queryset: The Django queryset to group
        group_by_field: The ApplicationField to group by
        
    Returns:
        A list of dicts with 'value', 'label', and 'items' keys
    """
    field_name = group_by_field.field
    field_type = group_by_field.field_type
    
    # Get unique values for the grouping field
    # For ForeignKey fields, we need to handle differently
    if field_type in ['ForeignKey', 'OneToOneField']:
        # Group by the related object
        grouped_data = defaultdict(list)
        for obj in queryset:
            related_obj = getattr(obj, field_name, None)
            # Use the related object's pk as key, or None for empty
            key = related_obj.pk if related_obj else None
            grouped_data[key].append(obj)
        
        # Build the groups list
        groups = []
        
        # Add a group for items with no value (None)
        if None in grouped_data:
            groups.append({
                'value': None,
                'label': 'Unassigned',
                'items': grouped_data[None],
                'count': len(grouped_data[None]),
            })
        
        # Get unique related objects
        related_model = group_by_field.related_model.model_class() if group_by_field.related_model else None
        if related_model:
            # Get all related objects that are referenced
            related_pks = [pk for pk in grouped_data.keys() if pk is not None]
            related_objects = {obj.pk: obj for obj in related_model.objects.filter(pk__in=related_pks)}
            
            for pk, items in grouped_data.items():
                if pk is not None:
                    related_obj = related_objects.get(pk)
                    groups.append({
                        'value': pk,
                        'label': str(related_obj) if related_obj else f'ID: {pk}',
                        'items': items,
                        'count': len(items),
                    })
    else:
        # For regular fields (CharField with choices, BooleanField, etc.)
        grouped_data = defaultdict(list)
        for obj in queryset:
            value = getattr(obj, field_name, None)
            grouped_data[value].append(obj)
        
        groups = []
        
        # Try to get choices from the model field
        model = queryset.model
        model_field = model._meta.get_field(field_name) if hasattr(model, '_meta') else None
        choices_dict = {}
        if model_field and hasattr(model_field, 'choices') and model_field.choices:
            choices_dict = dict(model_field.choices)
        
        # Add None group first if it exists
        if None in grouped_data or '' in grouped_data:
            none_items = grouped_data.get(None, []) + grouped_data.get('', [])
            if none_items:
                groups.append({
                    'value': None,
                    'label': 'Unassigned',
                    'items': none_items,
                    'count': len(none_items),
                })
        
        for value, items in grouped_data.items():
            if value is not None and value != '':
                label = choices_dict.get(value, str(value)) if choices_dict else str(value)
                groups.append({
                    'value': value,
                    'label': label,
                    'items': items,
                    'count': len(items),
                })
    
    return groups


# -----------------------------------
# Components
# -----------------------------------
@router.register(
    path="components/data_view/<int:content_type_id>/",
    name="components_data_view",
)
def data_view(request: HttpRequest, content_type_id: int, some_ctx:dict={}) -> HttpResponse:
    """
    Renders the data table component. A data table is a table that takes in a content type 
    id and renders a table of the corresponding model's data.
    It supports the following features:
    - filtering
    - permissions management
    - string searching
    """
    query = request.GET.get('q')
    page = request.GET.get('page', 1)
    
    # Get the content type
    try:
        content_type = ContentType.objects.get(id=content_type_id)
        Model = content_type.model_class()
    except ContentType.DoesNotExist:
        return HttpResponse("Content Type not found.", status=404)
    
    # Get the base queryset
    queryset = get_queryset_for_user(request.user, Model.objects.all())
    
    # Get the user's list view preference
    preference = get_user_list_view_preference(request.user, content_type)
    
    # Get fields for the user (visible + accessible)
    data_view_fields = get_data_view_fields(preference)
    
    # Apply string search if query is present
    if query:
        queryset = string_search_on_queryset(queryset, query)

    # Apply pagination
    page_size = preference.page_size
    paginator = Paginator(queryset, page_size)
    
    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    
    # Add extra context based on view type
    context = {
        'content_type_id': content_type_id,
        'queryset': page_obj,
        'page_obj': page_obj,
        'fields': data_view_fields,
        'preference': preference,
        'view_types': ViewType,
        'page_types': PageType,
        'page_sizes': PageSize,
    }
    context.update(_get_extra_context_for_view_type(preference, queryset))
    
    return render(request, 'components/objects/data_view.html', context)
    

@router.register(
    path="components/change_data_view_preference/<int:content_type_id>/",
    name="components_change_data_view_preference",
)
def change_data_view_preference(request: HttpRequest, content_type_id: int) -> HttpResponse:
    
    """Changes the datatable preference

    Args:
        request (HttpRequest): the request object
        content_type_id (int): The content type ID

    Returns:
        HttpResponse: the rendered datatable with the different preferences
    """
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)
    
    # Get the content type, user, and list view preference
    content_type = get_object_or_404(ContentType, id=content_type_id)
    user = request.user
    preference, _ = UserListViewPreference.objects.get_or_create(
        user=user,
        content_type=content_type)
    
    
    if "view_type" in request.POST:
        view_type = request.POST["view_type"]
        if view_type not in ViewType.values:
            return HttpResponse("Invalid view type", status=400)
        preference.view_type = view_type
    
    if "page_size" in request.POST:
        try:
            page_size = int(request.POST["page_size"])
            preference.page_size = page_size
        except ValueError:
            return HttpResponse("Invalid page size", status=400)    
    
    if "page_type" in request.POST:
        page_type = request.POST["page_type"]
        if page_type not in PageType.values:
            return HttpResponse("Invalid page type", status=400)
        preference.page_type = page_type

    if "split_view_enabled" in request.POST:
        split_view_enabled = request.POST["split_view_enabled"] == 'true'
        preference.split_view_enabled = split_view_enabled
        
    if "kanban_group_by" in request.POST:
        kanban_group_by = request.POST["kanban_group_by"]
        preference.kanban_group_by_field_id = int(kanban_group_by) if kanban_group_by != "no_grouping" else None

    # Handle field visibility toggle
    if "toggle_field_id" in request.POST:
        try:
            field_id = int(request.POST["toggle_field_id"])
            view_type = request.POST.get("toggle_view_type", preference.view_type)
            is_visible, preference = toggle_field_visibility(user, content_type, field_id, view_type)
        except (ValueError, ApplicationField.DoesNotExist) as e:
            return HttpResponse(f"Invalid field: {e}", status=400)
    else:
        # Save preference if no field toggle (field toggle already saves)
        preference.save()
    
    return data_view(request, content_type_id, {})
