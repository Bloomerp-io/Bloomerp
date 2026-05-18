from django.forms import modelform_factory
from django import forms
from django.shortcuts import get_object_or_404, render
from bloomerp.components.application_fields.filters import filters_init
from bloomerp.utils.requests import render_message
from bloomerp.router import router
from django.http import HttpResponse
from django.http import HttpRequest
from django.http import JsonResponse
from django.contrib.contenttypes.models import ContentType
from bloomerp.services.permission_services import UserPermissionManager
from bloomerp.services.permission_services import create_permission_str
from bloomerp.services.user_services import get_data_view_fields
from bloomerp.services.user_services import get_user_list_view_preference
from bloomerp.services.user_services import toggle_field_visibility
from bloomerp.services.object_services import string_search_on_queryset
from bloomerp.utils.filters import filter_model
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.models.users.user_list_view_preference import ViewType
from bloomerp.models.users.user_list_view_preference import PageType
from bloomerp.models.users.user_list_view_preference import PageSize
from bloomerp.models.users.user_list_view_preference import CalendarViewMode
from bloomerp.models import ApplicationField
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from collections import defaultdict
from django.db.models import Count, Q, QuerySet
from datetime import date, datetime, timedelta
from dataclasses import dataclass
import uuid

from bloomerp.utils.stopwatch import Stopwatch

# -----------------------------------
# Filter helpers
# -----------------------------------
RESERVED_FILTER_KEYS = {
    "q",
    "page",
    "calendar_page",
    "sort",
    "direction",
    "_component_id",
}

SORT_DIRECTIONS = {"asc", "desc"}

LOOKUP_LABELS = {
    "exact": "is",
    "equals": "is",
    "icontains": "contains",
    "contains": "contains",
    "startswith": "starts with",
    "endswith": "ends with",
    "gte": "≥",
    "lte": "≤",
    "gt": ">",
    "lt": "<",
    "isnull": "is empty",
    "in": "in",
    "year": "year is",
    "month": "month is",
    "day": "day is",
    "week": "week is",
    "today": "is today",
    "yesterday": "was yesterday",
    "this_week": "is in this week",
    "last_week": "is in last week",
    "this_month": "is in this month",
    "last_month": "is in last month",
    "this_quarter": "is in this quarter",
    "last_quarter": "is in last quarter",
    "this_year": "is in this year",
    "last_year": "is in last year",
}


def _humanize_field_path(value: str) -> str:
    parts = [part for part in value.split("__") if part]
    labels = [part.replace("_", " ").title() for part in parts]
    return " \u2192 ".join(labels)


def _format_applied_filters(query_params) -> list[dict]:
    # TODO: formatting function is also implemented in the frontend, we should unify this logic by moving this to the frontend
    # we can do so by just creating a component which onload formats the applied filters or something like that
    applied = []

    for key in query_params.keys():
        if key in RESERVED_FILTER_KEYS or key.startswith("_arg_"):
            continue

        values = query_params.getlist(key)
        if not values:
            continue

        raw_value = ", ".join([str(v) for v in values if v != ""])
        if raw_value == "":
            continue

        parts = [part for part in key.split("__") if part]
        lookup = None
        field_path = key
        if len(parts) > 1 and parts[-1] in LOOKUP_LABELS:
            lookup = parts[-1]
            field_path = "__".join(parts[:-1])

        field_label = _humanize_field_path(field_path)
        lookup_label = LOOKUP_LABELS.get(lookup, lookup or "is")

        if lookup == "isnull":
            lowered = raw_value.lower()
            if lowered in {"true", "1", "yes"}:
                label = f"{field_label} is empty"
            else:
                label = f"{field_label} has value"
        elif lookup in {"today", "yesterday", "this_week", "last_week", "this_month", "last_month", "this_quarter", "last_quarter", "this_year", "last_year"}:
            label = f"{field_label} {lookup_label}"
        else:
            label = f"{field_label} {lookup_label} {raw_value}"

        applied.append({
            "key": key,
            "label": label,
            "tooltip": f"{key} = {raw_value}",
        })

    return applied

# -----------------------------------
# Paginator
# -----------------------------------
@dataclass
class DataViewPagination:
    """Pagination state for the current data view render."""
    queryset: QuerySet
    page_obj: object | None = None
    pagination_pages: list[int | None] | None = None
    show_global_pagination: bool = False


@dataclass
class DataViewQueryState:
    content_type: ContentType
    model: type
    preference: UserListViewPreference
    data_view_fields: object
    data_view_render_fields: list[ApplicationField]
    avatar_field: ApplicationField | None
    queryset: QuerySet
    query: str | None
    sort_context: dict


class DataViewPaginationStrategy:
    """Base hook for view-specific pagination behavior."""

    def paginate(self, queryset: QuerySet, preference: UserListViewPreference, request: HttpRequest) -> DataViewPagination:
        return DataViewPagination(queryset=queryset)


class GlobalPagePaginationStrategy(DataViewPaginationStrategy):
    """Classic whole-queryset pagination used by table-like views."""

    def paginate(self, queryset: QuerySet, preference: UserListViewPreference, request: HttpRequest) -> DataViewPagination:
        page_obj = _paginate_object_list(queryset, preference.page_size, request.GET.get("page", 1))
        return DataViewPagination(
            queryset=page_obj,
            page_obj=page_obj,
            pagination_pages=_build_pagination_range(page_obj),
            show_global_pagination=True,
        )


class KanbanColumnPaginationStrategy(DataViewPaginationStrategy):
    """Kanban paginates inside each column, so the base queryset remains intact."""

    def paginate(self, queryset: QuerySet, preference: UserListViewPreference, request: HttpRequest) -> DataViewPagination:
        return DataViewPagination(queryset=queryset, show_global_pagination=False)


VIEW_PAGINATION_STRATEGIES: dict[str, DataViewPaginationStrategy] = {
    ViewType.TABLE: GlobalPagePaginationStrategy(),
    ViewType.CARD: GlobalPagePaginationStrategy(),
    ViewType.KANBAN: KanbanColumnPaginationStrategy(),
}


def _get_pagination_strategy(view_type: str) -> DataViewPaginationStrategy:
    return VIEW_PAGINATION_STRATEGIES.get(view_type, DataViewPaginationStrategy())


def _paginate_object_list(object_list, page_size: int, page_number):
    paginator = Paginator(object_list, page_size)

    try:
        return paginator.page(page_number)
    except PageNotAnInteger:
        return paginator.page(1)
    except EmptyPage:
        return paginator.page(paginator.num_pages or 1)


def _build_data_view_query_state(request: HttpRequest, content_type_id: int) -> DataViewQueryState | HttpResponse:
    query = request.GET.get('q')

    try:
        content_type = ContentType.objects.get(id=content_type_id)
        Model = content_type.model_class()
    except ContentType.DoesNotExist:
        return HttpResponse("Content Type not found.", status=404)

    permission_manager = UserPermissionManager(request.user)
    queryset = permission_manager.get_queryset(Model, create_permission_str(Model, "view"))

    preference = get_user_list_view_preference(request.user, content_type)
    data_view_fields = get_data_view_fields(preference)
    avatar_field, data_view_render_fields = _split_avatar_field(data_view_fields)

    if query:
        queryset = string_search_on_queryset(queryset, query)

    filter_querydict = request.GET.copy()
    for key in ('page', 'calendar_page', 'kanban_page', 'kanban_column', 'sort', 'direction', '_component_id'):
        filter_querydict.pop(key, None)
    for key in list(filter_querydict.keys()):
        if key.startswith("_arg_"):
            filter_querydict.pop(key, None)
    queryset = filter_model(Model, filter_querydict, queryset)

    sort_context = {}
    if preference.view_type == ViewType.TABLE:
        queryset, sort_context = _apply_table_sorting(queryset, request, data_view_fields)

    return DataViewQueryState(
        content_type=content_type,
        model=Model,
        preference=preference,
        data_view_fields=data_view_fields,
        data_view_render_fields=data_view_render_fields,
        avatar_field=avatar_field,
        queryset=queryset,
        query=query,
        sort_context=sort_context,
    )



# -----------------------------------
# Helper functions for different view types
# -----------------------------------
def _build_pagination_range(page_obj, window: int = 2) -> list[int | None]:
    """Build a pagination range with ellipses for UI rendering."""
    paginator = page_obj.paginator
    total_pages = paginator.num_pages
    current_page = page_obj.number

    if total_pages <= 1:
        return [1]

    pages: list[int | None] = []

    def add_page(page_number: int) -> None:
        pages.append(page_number)

    def add_ellipsis() -> None:
        if pages and pages[-1] is not None:
            pages.append(None)

    add_page(1)

    start = max(2, current_page - window)
    end = min(total_pages - 1, current_page + window)

    if start > 2:
        add_ellipsis()

    for page_number in range(start, end + 1):
        add_page(page_number)

    if end < total_pages - 1:
        add_ellipsis()

    add_page(total_pages)

    return pages


def _apply_table_sorting(queryset: QuerySet, request: HttpRequest, data_view_fields) -> tuple[QuerySet, dict]:
    sort_field = request.GET.get("sort")
    sort_direction = request.GET.get("direction", "asc")
    visible_fields_by_name = {
        field.field: field
        for field in data_view_fields.visible_fields
    }

    context = {
        "current_sort_field": "",
        "current_sort_direction": "",
    }

    if not sort_field or sort_direction not in SORT_DIRECTIONS:
        return queryset, context

    if sort_field not in visible_fields_by_name:
        return queryset, context

    sort_expression = sort_field if sort_direction == "asc" else f"-{sort_field}"
    queryset = queryset.order_by(sort_expression, "pk")
    context.update({
        "current_sort_field": sort_field,
        "current_sort_direction": sort_direction,
    })
    return queryset, context


def _split_avatar_field(data_view_fields) -> tuple[ApplicationField | None, list[ApplicationField]]:
    avatar_field = None
    fields = []

    for field in data_view_fields.visible_fields:
        if field.field == "avatar":
            avatar_field = field
            continue
        fields.append(field)

    return avatar_field, fields


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
                kanban_groups = _build_kanban_groups(
                    queryset,
                    kanban_group_by_field,
                    page_size=preference.page_size,
                )
            
            context["kanban_groups"] = kanban_groups
            context["kanban_group_by_field"] = kanban_group_by_field
            
        case ViewType.CARD:
            pass

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
    
    
KANBAN_EMPTY_COLUMN_VALUE = "__none__"


def _format_kanban_column_value(value) -> str:
    return KANBAN_EMPTY_COLUMN_VALUE if value in (None, "") else str(value)


def _get_kanban_model_field(queryset, field_name: str):
    model = queryset.model
    if not hasattr(model, '_meta'):
        return None

    try:
        return model._meta.get_field(field_name)
    except Exception:
        return None


def _iter_kanban_choices(choices):
    for choice_value, choice_label in choices:
        if isinstance(choice_label, (list, tuple)):
            for nested_value, nested_label in choice_label:
                yield nested_value, nested_label
        else:
            yield choice_value, choice_label


def _kanban_field_allows_blank_string(model_field) -> bool:
    return bool(
        model_field
        and getattr(model_field, 'empty_strings_allowed', False)
        and not (getattr(model_field, 'many_to_one', False) or getattr(model_field, 'one_to_one', False))
    )


def _build_kanban_empty_filter(field_name: str, model_field) -> Q:
    empty_filter = Q(**{f"{field_name}__isnull": True})
    if _kanban_field_allows_blank_string(model_field):
        empty_filter |= Q(**{field_name: ""})
    return empty_filter


def _coerce_kanban_column_value(raw_value: str, model_field):
    if raw_value == KANBAN_EMPTY_COLUMN_VALUE:
        return None

    if model_field is None:
        return raw_value

    try:
        if getattr(model_field, 'many_to_one', False) or getattr(model_field, 'one_to_one', False):
            return model_field.target_field.to_python(raw_value)
        return model_field.to_python(raw_value)
    except Exception:
        return raw_value


def _get_kanban_choice_label(model_field, value) -> str:
    if model_field and getattr(model_field, 'choices', None):
        for choice_value, choice_label in _iter_kanban_choices(model_field.choices):
            if choice_value == value:
                return str(choice_label)

    return str(value)


def _get_kanban_related_label(queryset, field_name: str, value) -> str:
    related_obj = (
        queryset
        .filter(**{field_name: value})
        .select_related(field_name)
        .first()
    )
    if related_obj:
        related_value = getattr(related_obj, field_name, None)
        if related_value:
            return str(related_value)

    return f'ID: {value}'


def _build_kanban_column_queryset(queryset, field_name: str, model_field, value):
    if value is None:
        return queryset.filter(_build_kanban_empty_filter(field_name, model_field))
    return queryset.filter(**{field_name: value})


def _build_kanban_column_group(
    queryset,
    group_by_field: ApplicationField,
    column_value: str,
    page_size: int | None = None,
    page_number=1,
) -> dict | None:
    field_name = group_by_field.field
    field_type = group_by_field.field_type
    model_field = _get_kanban_model_field(queryset, field_name)
    value = _coerce_kanban_column_value(column_value, model_field)

    column_queryset = _build_kanban_column_queryset(queryset, field_name, model_field, value)
    item_count = column_queryset.count()
    if item_count == 0 and value is not None:
        return None

    if value is None:
        label = 'Unassigned'
    elif field_type in ['ForeignKey', 'OneToOneField']:
        label = _get_kanban_related_label(queryset, field_name, value)
    else:
        label = _get_kanban_choice_label(model_field, value)

    return _build_kanban_group(
        value,
        label,
        column_queryset,
        page_size,
        page_number,
        item_count=item_count,
    )


def _build_kanban_group(
    value,
    label: str,
    items: list,
    page_size: int | None = None,
    page_number=1,
    item_count: int | None = None,
) -> dict:
    """Build a kanban group with optimized performance.
    
    Args:
        value: The group value/identifier
        label: The group label for display
        items: List of items in this group
        page_size: Optional page size for pagination
        page_number: Current page number for pagination
        item_count: Pre-calculated item count (avoids len() call if provided)
    
    Returns:
        Dictionary representing the kanban group
    """
    # Pre-calculated count is more efficient than calling len(items) each time
    total_count = item_count if item_count is not None else len(items)
    
    # Only paginate if needed
    if page_size:
        page_obj = _paginate_object_list(items, page_size, page_number)
        visible_items = page_obj.object_list  # Keep as paginator object_list, don't convert to list
    else:
        page_obj = None
        visible_items = items

    return {
        'value': value,
        'request_value': _format_kanban_column_value(value),
        'label': label,
        'items': visible_items,
        'count': total_count,
        'page_obj': page_obj,
        'has_next_page': page_obj.has_next() if page_obj else False,
        'next_page_number': page_obj.next_page_number() if page_obj and page_obj.has_next() else None,
    }


def _build_kanban_groups(queryset, group_by_field: ApplicationField, page_size: int | None = None, page_number=1) -> list[dict]:
    """
    Builds kanban groups from a queryset based on a grouping field.
    Optimized to minimize database queries and Python object iteration.
    
    Args:
        queryset: The Django queryset to group
        group_by_field: The ApplicationField to group by
        page_size: Optional page size for pagination
        page_number: Current page number (1-indexed)
        
    Returns:
        A list of dicts with 'value', 'label', and 'items' keys
    """
    field_name = group_by_field.field
    field_type = group_by_field.field_type
    model_field = _get_kanban_model_field(queryset, field_name)
    groups = []
    
    if field_type in ['ForeignKey', 'OneToOneField']:
        count_rows = list(
            queryset
            .values(field_name)
            .annotate(item_count=Count('pk'))
            .order_by(field_name)
        )
        counts_by_value = {
            row[field_name]: row["item_count"]
            for row in count_rows
        }

        if None in counts_by_value:
            items = _build_kanban_column_queryset(queryset, field_name, model_field, None)
            groups.append(_build_kanban_group(
                None, 'Unassigned', items, page_size, page_number,
                item_count=counts_by_value[None]
            ))

        related_labels = {}
        if model_field and getattr(model_field, 'remote_field', None):
            related_model = model_field.remote_field.model
            related_values = [value for value in counts_by_value if value is not None]
            related_labels = {
                pk: str(related_obj)
                for pk, related_obj in related_model.objects.in_bulk(related_values).items()
            }

        for row in count_rows:
            value = row[field_name]
            if value is not None:
                items = _build_kanban_column_queryset(queryset, field_name, model_field, value)
                label = related_labels.get(value, f'ID: {value}')
                groups.append(_build_kanban_group(
                    value, label, items, page_size, page_number,
                    item_count=row["item_count"]
                ))
    else:
        empty_count = queryset.filter(_build_kanban_empty_filter(field_name, model_field)).count()
        if empty_count:
            items = _build_kanban_column_queryset(queryset, field_name, model_field, None)
            groups.append(_build_kanban_group(
                None, 'Unassigned', items, page_size, page_number,
                item_count=empty_count
            ))

        if model_field and getattr(model_field, 'choices', None):
            seen_values = set()
            counts_by_value = {
                row[field_name]: row["item_count"]
                for row in (
                    queryset
                    .exclude(_build_kanban_empty_filter(field_name, model_field))
                    .values(field_name)
                    .annotate(item_count=Count('pk'))
                    .order_by(field_name)
                )
            }

            # Always render every configured choice in declaration order.
            for choice_value, choice_label in _iter_kanban_choices(model_field.choices):
                if choice_value in (None, ''):
                    continue

                choice_items = _build_kanban_column_queryset(queryset, field_name, model_field, choice_value)
                groups.append(_build_kanban_group(
                    choice_value, str(choice_label), choice_items, page_size, page_number,
                    item_count=counts_by_value.get(choice_value, 0)
                ))
                seen_values.add(choice_value)

            # Include unexpected values from data so cards never disappear.
            for value, item_count in counts_by_value.items():
                if value in seen_values:
                    continue
                items = _build_kanban_column_queryset(queryset, field_name, model_field, value)
                groups.append(_build_kanban_group(
                    value, str(value), items, page_size, page_number,
                    item_count=item_count
                ))
        else:
            count_rows = (
                queryset
                .exclude(_build_kanban_empty_filter(field_name, model_field))
                .values(field_name)
                .annotate(item_count=Count('pk'))
                .order_by(field_name)
            )
            for row in count_rows:
                value = row[field_name]
                items = _build_kanban_column_queryset(queryset, field_name, model_field, value)
                groups.append(_build_kanban_group(
                    value, str(value), items, page_size, page_number,
                    item_count=row["item_count"]
                ))
    
    return groups


def _get_component_args(request:HttpRequest) -> dict[str, str]:
    """Returns the component args

    Args:
        request (HttpRequest): the request object

    Returns:
        dict[str, str]: the parsed arguments
    """
    args = {}
    for arg, value in request.GET.items():
        if arg.startswith("_arg_"):
            cleaned_arg = arg[5:].lower().replace("_","-")
            args[cleaned_arg] = value
    
    return args


# -----------------------------------
# Components
# -----------------------------------
@router.register(
    path="components/data_view/<int:content_type_id>/",
    name="components_data_view",
)
def data_view(request: HttpRequest, content_type_id: int) -> HttpResponse:
    """
    Renders the data table component. A data table is a table that takes in a content type 
    id and renders a table of the corresponding model's data.
    It supports the following features:
    - filtering
    - permissions management
    - string searching
    """
    state = _build_data_view_query_state(request, content_type_id)
    if isinstance(state, HttpResponse):
        return state
    
    preference = state.preference
    queryset = state.queryset
    query = state.query
    data_view_fields = state.data_view_fields
    data_view_render_fields = state.data_view_render_fields
    avatar_field = state.avatar_field
    sort_context = state.sort_context
    
    pagination = _get_pagination_strategy(preference.view_type).paginate(queryset, preference, request)
    
    # Add extra context based on view type
    # TODO: take a look at this logic, it looks a little bit weird
    page_querystring = request.GET.copy()
    page_querystring.pop('page', None)
    kanban_page_querystring = request.GET.copy()
    kanban_page_querystring.pop('page', None)
    kanban_page_querystring.pop('kanban_page', None)
    kanban_page_querystring.pop('kanban_column', None)
    table_sort_querystring = request.GET.copy()
    table_sort_querystring.pop('page', None)
    table_sort_querystring.pop('sort', None)
    table_sort_querystring.pop('direction', None)
    search_querystring = request.GET.copy()
    search_querystring.pop('page', None)
    search_querystring.pop('q', None)
    search_querystring.pop('calendar_page', None)
    create_querystring = request.GET.copy()
    create_querystring.pop('page', None)
    create_querystring.pop('q', None)
    create_querystring.pop('calendar_page', None)
    export_querystring = request.GET.copy()
    export_querystring.pop('page', None)
    export_querystring.pop('calendar_page', None)
    export_querystring.pop('_component_id', None)
    sync_url = request.headers.get("X-Bloomerp-Sync-Url", "false").lower() == "true"
    component_id = request.GET.get('_component_id')

    context = {
        'content_type_id': content_type_id,
        'queryset': pagination.queryset,
        'page_obj': pagination.page_obj,
        'fields': data_view_fields,
        'data_view_render_fields': data_view_render_fields,
        'avatar_field': avatar_field,
        'preference': preference,
        'view_types': ViewType,
        'page_types': PageType,
        'page_sizes': PageSize,
        'calendar_view_modes': CalendarViewMode,
        'render_id': str(uuid.uuid4()),
        'search_query': query or '',
        'search_querystring': search_querystring.urlencode(),
        'create_querystring': create_querystring.urlencode(),
        'export_querystring': export_querystring.urlencode(),
        'sync_url': sync_url,
        'filter_section' : filters_init(request, content_type_id).content.decode("utf-8"), # TODO: optimize because of multiple queries
        'page_querystring': page_querystring.urlencode(),
        'kanban_page_querystring': kanban_page_querystring.urlencode(),
        'table_sort_querystring': table_sort_querystring.urlencode(),
        'pagination_pages': pagination.pagination_pages or [],
        'show_global_pagination': pagination.show_global_pagination,
        'applied_filters': _format_applied_filters(request.GET),
        'component_id': component_id,
        'component_args' : _get_component_args(request)
    }
    context.update(sort_context)
    context.update(_get_extra_context_for_view_type(preference, queryset, request))
    
    return render(request, 'components/objects/dataview.html', context)


@router.register(
    path="components/data_view/<int:content_type_id>/kanban_column/",
    name="components_data_view_kanban_column",
)
def data_view_kanban_column(request: HttpRequest, content_type_id: int) -> HttpResponse:
    """Renders one additional page for a kanban column."""
    
    state = _build_data_view_query_state(request, content_type_id)
    
    if isinstance(state, HttpResponse):
        return state

    preference = state.preference
    if preference.view_type != ViewType.KANBAN or not preference.kanban_group_by_field:
        return HttpResponse("Kanban grouping is not configured.", status=400)

    column_value = request.GET.get("kanban_column")
    if not column_value:
        return HttpResponse("Missing kanban column.", status=400)

    page_number = request.GET.get("kanban_page", 1)
    
    group = _build_kanban_column_group(
        state.queryset,
        preference.kanban_group_by_field,
        column_value,
        page_size=preference.page_size,
        page_number=page_number,
    )
    
    if group is None:
        return HttpResponse("Kanban column not found.", status=404)
    
    
    kanban_page_querystring = request.GET.copy()
    kanban_page_querystring.pop('page', None)
    kanban_page_querystring.pop('kanban_page', None)
    kanban_page_querystring.pop('kanban_column', None)

    
    return render(
        request,
        'components/objects/dataview_kanban_cards.html',
        {
            'content_type_id': content_type_id,
            'fields': state.data_view_render_fields,
            'avatar_field': state.avatar_field,
            'group': group,
            'kanban_page_querystring': kanban_page_querystring.urlencode(),
        },
    )
    

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
    preference = UserListViewPreference.get_or_create_for_user(
        user=user,
        content_type_or_model=content_type,
    )
    
    
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
            permission_manager = UserPermissionManager(request.user)
            
            if not permission_manager.has_field_permission(
                ApplicationField.objects.get(id=field_id),
                create_permission_str(content_type.model_class(), "view")
            ):
                return HttpResponse("Permission denied", status=403)
            
            is_visible, preference = toggle_field_visibility(user, content_type, field_id, view_type)
        except (ValueError, ApplicationField.DoesNotExist) as e:
            return HttpResponse(f"Invalid field: {e}", status=400)
    else:
        # Save preference if no field toggle (field toggle already saves)
        preference.save()
    
    return data_view(request, content_type_id)


@router.register(
    path="components/dataview_edit_field/<int:application_field_id>/<str:object_id>/",
    name="components_dataview_edit_field",
)
def dataview_edit_field(request: HttpRequest, application_field_id:int, object_id: str) -> HttpResponse:
    """Renders the inline edit component for a dataview field.

    Args:
        request (HttpRequest): The request object.
        application_field_id (int): The application field ID to edit.

    Returns:
        HttpResponse: The rendered inline edit component.
    """
    # Retrieve the objects
    application_field = get_object_or_404(ApplicationField, id=application_field_id)
    model = application_field.get_model()
    object = get_object_or_404(application_field.get_model(), id=object_id)
    permission_str = f"change_{model._meta.model_name}"
    
    manager = UserPermissionManager(request.user)
    if not manager.has_access_to_object(object, permission_str):
        return HttpResponse(status=405)
    
    if not manager.has_field_permission(application_field, permission_str):
        return HttpResponse(status=405)
    
    if request.method == "GET":
        widget = application_field.get_widget()
        widget_choices = getattr(widget, "get_choices", lambda *_args, **_kwargs: [])()
        input_class = "select select-sm w-full bg-transparent border-0" if isinstance(widget, forms.Select) or widget_choices else "border-0 w-full bg-transparent input-sm"
        
        return HttpResponse(
            widget.render(
                name=application_field.field,
                value=getattr(object, application_field.field),
                attrs={
                    "class" : input_class,
                }
        ))
    elif request.method == "POST":
        FormCls = modelform_factory(
            model,
            fields=[application_field.field],
        )
        form = FormCls(request.POST, instance=object)
        if form.is_valid():
            form.save()
            return render_message(request, "Field updated successfully", "success")
        else:
            pass
            

@router.register(
    path="components/kanban_move_card/<int:content_type_id>/",
    name="components_kanban_move_card",
)
def kanban_move_card(request: HttpRequest, content_type_id: int) -> HttpResponse:
    """Updates a kanban card's grouping field value.

    Expects POST data:
        object_id: the model instance ID to update
        group_by_field_id: ApplicationField ID used for kanban grouping
        group_value: the new value for the grouping field (or "__none__")
    """
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    object_id = request.POST.get("object_id")
    group_by_field_id = request.POST.get("group_by_field_id")
    group_value = request.POST.get("group_value")

    if not object_id or not group_by_field_id:
        return HttpResponse("Missing required fields", status=400)

    content_type = get_object_or_404(ContentType, id=content_type_id)
    model = content_type.model_class()
    if model is None:
        return HttpResponse("Invalid content type", status=400)

    application_field = get_object_or_404(
        ApplicationField,
        id=group_by_field_id,
        content_type=content_type
    )

    obj = get_object_or_404(model, id=object_id)
    permission_str = create_permission_str(model, "change")

    permission_manager = UserPermissionManager(request.user)
    if not permission_manager.has_access_to_object(obj, permission_str):
        return HttpResponse("Permission denied", status=403)
    if not permission_manager.has_field_permission(application_field, permission_str):
        return HttpResponse("Permission denied", status=403)

    model_field = model._meta.get_field(application_field.field)

    normalized_value = None if group_value in (None, "", "__none__") else group_value
    if normalized_value is None:
        if not model_field.null and not model_field.blank:
            return HttpResponse("Field does not allow empty values", status=400)
        setattr(obj, application_field.field, None)
    else:
        try:
            if model_field.many_to_one or model_field.one_to_one:
                related_model = model_field.remote_field.model
                related_obj = related_model.objects.get(pk=normalized_value)
                setattr(obj, application_field.field, related_obj)
            else:
                typed_value = model_field.to_python(normalized_value)
                setattr(obj, application_field.field, typed_value)
        except Exception as exc:
            return HttpResponse(f"Invalid value: {exc}", status=400)

    obj.save(update_fields=[application_field.field])

    return JsonResponse({"status": "ok"})
    

    
    
