"""Render or page a server-scoped Inbox calendar with the existing dataview."""

from django.core.exceptions import PermissionDenied
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET

from bloomerp.communication.calendar.calendar_access import resolve_calendar_inbox
from bloomerp.communication.calendar.inbox_renderer import InboxCalendarRenderer
from bloomerp.dataviews.calendar.config import CalendarDataView
from bloomerp.dataviews.calendar.renderer import CALENDAR_PAGE_SIZE, CALENDAR_VIEW_MODES
from bloomerp.dataviews.definition import DataviewPagination, DataviewState
from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.services.user_services import DataViewFields


@router.register(
    path="components/communication/inbox/<int:inbox_id>/calendar/",
    url_name="components_inbox_calendar",
)
@login_required
@require_GET
def inbox_calendar(request: HttpRequest, inbox_id: int) -> HttpResponse:
    """Recheck Inbox and event policies on every period, search, and load-more request."""
    inbox = resolve_calendar_inbox(request.user, inbox_id)
    manager = UserPolicyManager(request.user)
    readable = set(manager.get_accessible_fields(CalendarEvent, "view").values_list("field", flat=True))
    if not {"inboxes", "all_day", "cancelled"} <= readable or not (
        {"start", "end"} <= readable or {"start_date", "end_date"} <= readable
    ):
        raise PermissionDenied("Calendar date and placement permissions are required")
    content_type = ContentType.objects.get_for_model(CalendarEvent)
    queryset = (
        manager.get_accessible_queryset(CalendarEvent, "view")
        .filter(inboxes=inbox, cancelled=False)
        .distinct()
    )
    query = request.GET.get("q", "")
    if query:
        queryset = queryset.filter(title__icontains=query)
    mode = request.GET.get("calendar_view_mode", "week")
    if mode not in CALENDAR_VIEW_MODES:
        return HttpResponse("Invalid calendar view mode", status=400)
    try:
        if abs(int(request.GET.get("calendar_page", 0))) > 1200:
            raise ValueError
    except ValueError:
        return HttpResponse("Invalid calendar page", status=400)
    options = CalendarDataView(start_field="start", end_field="end", view_mode=mode)
    accessible = list(manager.get_accessible_fields(CalendarEvent, "view"))
    fields = DataViewFields(
        visible_fields=[], accessible_fields=[(field, False) for field in accessible]
    )
    # Rendering needs a preference-shaped object, but this view must not change saved preferences.
    preference = UserListViewPreference(
        pk=0,
        user=request.user,
        content_type=content_type,
        view_type="calendar",
        view_mode="normal",
    )
    state = DataviewState(
        request=request,
        model=CalendarEvent,
        content_type=content_type,
        preference=preference,
        queryset=queryset,
        fields=fields,
        render_fields=[],
        avatar_field=None,
        options=options,
    )
    endpoint = reverse("components_inbox_calendar", kwargs={"inbox_id": inbox.pk})
    state.context = {"calendar_mode_url": endpoint, "calendar_unit_url": endpoint}
    renderer = InboxCalendarRenderer(state)
    if "calendar_unit" in request.GET:
        unit = request.GET["calendar_unit"]
        try:
            offset = int(request.GET.get("calendar_unit_offset", CALENDAR_PAGE_SIZE))
            start, end = renderer.unit_period(unit, mode)
        except (ValueError, OverflowError):
            return HttpResponse("Invalid calendar unit", status=400)
        if offset < 0:
            return HttpResponse("Invalid calendar offset", status=400)
        start_field = next(
            (field for field in accessible if field.field == "start"), None
        )
        if start_field is None:
            # Date-only readers can still page all-day meetings with the shared renderer.
            start_field = next(
                field for field in accessible if field.field == "start_date"
            )
        objects = renderer._filter_period_queryset(
            queryset, start_field, None, start, end
        )
        events, _ = renderer._build_events(objects, start_field, None, None)
        matching = renderer._group_events(events, mode, start, end).get(unit, [])
        page = matching[offset : offset + CALENDAR_PAGE_SIZE]
        querystring = request.GET.copy()
        for key in ("calendar_unit", "calendar_view_mode", "calendar_unit_offset"):
            querystring.pop(key, None)
        return render(
            request,
            "components/objects/dataview_calendar_events.html",
            {
                "content_type_id": content_type.pk,
                "preference": preference,
                "events": page,
                "fields": [],
                "calendar_unit": unit,
                "calendar_view_mode": mode,
                "calendar_next_unit_offset": offset + len(page),
                "calendar_has_more": offset + len(page) < len(matching),
                "calendar_page_querystring": querystring.urlencode(),
                "calendar_unit_url": endpoint,
            },
        )
    # The standard calendar needs a primary accessible date field to activate its grid.
    if not any(field.field == "start" for field in accessible):
        state.options = CalendarDataView(
            start_field="start_date", end_field="end_date", view_mode=mode
        )
        renderer = InboxCalendarRenderer(state)
    calendar = renderer.render(DataviewPagination(queryset=[]))
    if request.headers.get("HX-Target", "").lstrip("#") == "data-view-data-section":
        response = HttpResponse(calendar)
        if request.headers.get("X-Bloomerp-Inbox-Calendar-Mode") == "true":
            page_url = reverse("inbox_calendar", kwargs={"inbox_id": inbox.pk})
            page_query = request.GET.copy()
            for key in list(page_query):
                if key not in {"q", "calendar_page", "calendar_view_mode"}:
                    page_query.pop(key)
            response["HX-Push-Url"] = (
                f"{page_url}?{page_query.urlencode()}" if page_query else page_url
            )
        return response
    return render(
        request,
        "components/communication/calendar/inbox_calendar.html",
        {
            "calendar_html": calendar,
            "calendar_url": endpoint,
            "calendar_current_url": request.get_full_path(),
            "content_type_id": content_type.pk,
            "search_query": query,
        },
    )
