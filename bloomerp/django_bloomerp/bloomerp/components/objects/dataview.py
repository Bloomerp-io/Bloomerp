from django.shortcuts import get_object_or_404, render
from bloomerp.components.application_fields.filters import filters_init
from registries.route_registry import router
from django.http import HttpResponse
from django.http import HttpRequest
from django.contrib.contenttypes.models import ContentType
from bloomerp.services.permission_services import UserPermissionManager
from bloomerp.services.permission_services import create_permission_str
from bloomerp.services.user_services import get_data_view_fields
from bloomerp.services.user_services import get_user_list_view_preference
from bloomerp.services.user_services import toggle_field_visibility
from bloomerp.services.object_services import string_search_on_queryset
from bloomerp.utils.filters import dynamic_filterset_factory, filter_model
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.models.users.user_list_view_preference import ViewType
from bloomerp.models.users.user_list_view_preference import PageType
from bloomerp.models.users.user_list_view_preference import PageSize
from bloomerp.models.users.user_list_view_preference import CalendarViewMode
from bloomerp.models import ApplicationField
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from collections import defaultdict
from django.db.models import QuerySet
from datetime import date, datetime, timedelta
import uuid


# -----------------------------------
# Helper functions for different view types
# -----------------------------------
def _get_extra_context_for_view_type(preference:UserListViewPreference, queryset:QuerySet, request:HttpRequest) -> dict:
    """Returns the extra context for a particular view type.

    Args:
        preference (UserListViewPreference): the user's view preference
        queryset (QuerySet): the queryset to process
        request (HttpRequest): the request object for query params

    Returns:
        dict: extra context for the view type
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
            context.update(_build_calendar_context(preference, queryset, request))
        
        case ViewType.GANT:
            context.update(
                {
                    
                }
            )
        
        case _:
            pass
    
    return context


def _build_calendar_context(preference: UserListViewPreference, queryset: QuerySet, request: HttpRequest) -> dict:
    """
    Builds the calendar context from a queryset based on calendar preferences.
    
    Args:
        preference: The user's list view preference
        queryset: The Django queryset to display
        request: The HTTP request for query parameters
        
    Returns:
        dict: Calendar context including events grouped by date
    """
    today = date.today()
    
    context = {
        'calendar_start_field': preference.calendar_start_field,
        'calendar_end_field': preference.calendar_end_field,
        'calendar_view_mode': preference.calendar_view_mode,
        'calendar_view_modes': CalendarViewMode,
        'calendar_events': [],
        'calendar_date_range': None,
        'calendar_current_date': None,
        'calendar_today': today,
    }
    
    # If no start field is set, return empty context
    if not preference.calendar_start_field:
        return context
    
    field_name = preference.calendar_start_field.field
    view_mode = preference.calendar_view_mode
    
    # Get page offset from request (0 = current period, -1 = previous, 1 = next)
    try:
        page_offset = int(request.GET.get('calendar_page', 0))
    except ValueError:
        page_offset = 0
    
    # Calculate the date range based on view mode and page offset
    if view_mode == CalendarViewMode.DAY:
        current_date = today + timedelta(days=page_offset)
        start_date = current_date
        end_date = current_date
        # Generate list of hours for day view
        hours = list(range(0, 24))
        context['calendar_hours'] = hours
        
    elif view_mode == CalendarViewMode.WEEK:
        # Start of current week (Monday)
        week_start = today - timedelta(days=today.weekday())
        current_date = week_start + timedelta(weeks=page_offset)
        start_date = current_date
        end_date = start_date + timedelta(days=6)
        # Generate list of days for week view
        days = [start_date + timedelta(days=i) for i in range(7)]
        context['calendar_days'] = days
        # Generate hours for week view
        context['calendar_hours'] = list(range(0, 24))
        
    elif view_mode == CalendarViewMode.MONTH:
        # Start of current month
        first_of_month = today.replace(day=1)
        # Add/subtract months
        month_offset = page_offset
        year = first_of_month.year + (first_of_month.month - 1 + month_offset) // 12
        month = (first_of_month.month - 1 + month_offset) % 12 + 1
        current_date = date(year, month, 1)
        start_date = current_date
        # End of month
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)
        # Generate calendar grid (including days from prev/next month to fill weeks)
        calendar_weeks = _build_month_calendar_grid(start_date, end_date)
        context['calendar_weeks'] = calendar_weeks
    else:
        current_date = today
        start_date = today
        end_date = today
    
    context['calendar_current_date'] = current_date
    context['calendar_page_offset'] = page_offset
    context['calendar_date_range'] = {
        'start': start_date,
        'end': end_date,
    }
    
    # Filter queryset to events within the date range
    filter_kwargs = {
        f'{field_name}__gte': start_date,
        f'{field_name}__lte': end_date + timedelta(days=1),  # Include end date fully
    }
    
    try:
        filtered_queryset = queryset.filter(**filter_kwargs)
    except Exception:
        # Field might not support filtering this way
        filtered_queryset = queryset
    
    # Group events by date
    events_by_date = defaultdict(list)
    for obj in filtered_queryset:
        event_date_value = getattr(obj, field_name, None)
        if event_date_value:
            # Handle both date and datetime
            if isinstance(event_date_value, datetime):
                event_date = event_date_value.date()
                event_time = event_date_value.time()
            else:
                event_date = event_date_value
                event_time = None
            
            events_by_date[event_date].append({
                'object': obj,
                'date': event_date,
                'time': event_time,
                'datetime': event_date_value,
            })
    
    context['calendar_events_by_date'] = dict(events_by_date)
    context['calendar_events'] = list(filtered_queryset)
    
    return context


def _build_month_calendar_grid(start_date: date, end_date: date) -> list:
    """
    Builds a calendar grid for month view, including padding days from adjacent months.
    
    Args:
        start_date: First day of the month
        end_date: Last day of the month
        
    Returns:
        list: List of weeks, each week is a list of date objects
    """
    weeks = []
    
    # Find the Monday of the week containing the first day
    first_day_weekday = start_date.weekday()  # Monday = 0
    grid_start = start_date - timedelta(days=first_day_weekday)
    
    # Find the Sunday of the week containing the last day
    last_day_weekday = end_date.weekday()
    grid_end = end_date + timedelta(days=(6 - last_day_weekday))
    
    # Build weeks
    current_day = grid_start
    while current_day <= grid_end:
        week = []
        for _ in range(7):
            week.append({
                'date': current_day,
                'is_current_month': start_date <= current_day <= end_date,
                'is_today': current_day == date.today(),
            })
            current_day += timedelta(days=1)
        weeks.append(week)
    
    return weeks
    
    
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
    
    # Manager
    permission_manager = UserPermissionManager(request.user)
    
    # Get the base queryset
    queryset = permission_manager.get_queryset(Model, create_permission_str(Model, "view"))
    
    # Get the user's list view preference
    preference = get_user_list_view_preference(request.user, content_type)
    
    # Get fields for the user (visible + accessible)
    data_view_fields = get_data_view_fields(preference)
    print(data_view_fields)
    
    # Apply string search if query is present
    if query:
        queryset = string_search_on_queryset(queryset, query)

    # The model
    queryset = filter_model(Model, request.GET, queryset)
    
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
        'calendar_view_modes': CalendarViewMode,
        'render_id': str(uuid.uuid4()),
        'filter_section' : filters_init(request, content_type_id).content.decode("utf-8"), # TODO: optimize because of multiple queries
    }
    context.update(_get_extra_context_for_view_type(preference, queryset, request))
    
    return render(request, 'components/objects/dataview.html', context)
    

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

    if "calendar_start_field" in request.POST:
        calendar_start_field = request.POST["calendar_start_field"]
        preference.calendar_start_field_id = int(calendar_start_field) if calendar_start_field else None
    
    if "calendar_view_mode" in request.POST:
        calendar_view_mode = request.POST["calendar_view_mode"]
        if calendar_view_mode in [mode.value for mode in CalendarViewMode]:
            preference.calendar_view_mode = calendar_view_mode

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


@router.register(
    path="components/dataview_edit_field/<int:application_field_id>/<str:object_id>/",
    name="components_dataview_inline",
)
def dataview_edit_field(request: HttpRequest, application_field_id:int, object_id: str) -> HttpResponse:
    """Renders the inline edit component for a dataview field.

    Args:
        request (HttpRequest): The request object.
        application_field_id (int): The application field ID to edit.

    Returns:
        HttpResponse: The rendered inline edit component.
    """
    application_field = get_object_or_404(ApplicationField, id=application_field_id)
    
    if not has_access_to_field(request.user, application_field):
        # TODO: Handle pass response
        pass
    
    # Steps:
    # Validate whether the application field is editable
    # 1. Get the model and object
    # 2. Get the field type based on the application field
    # 3. Render the appropriate based on the field type
    # 4. Make sure the rendered component has an onchange that saves the value via an API call
    
    return HttpResponse("<input value='Hello world'>")
    

    
    