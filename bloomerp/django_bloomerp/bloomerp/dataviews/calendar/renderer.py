from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from functools import partial
from typing import TYPE_CHECKING, Any, ClassVar

from django.core.exceptions import FieldDoesNotExist
from django.db import IntegrityError, transaction
from django.db.models import Model, Prefetch, Q, QuerySet
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import get_model_config
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager, field_access_annotation_name
from bloomerp.services.preference_services import PreferenceManager

from ..definition import BaseDataviewRenderer, DataviewState
from ..gant.renderer import GanttDataviewRenderer
from ..unscheduled import UnscheduledDataviewMixin

if TYPE_CHECKING:
    from bloomerp.models.definition import DataviewActionContext
    from bloomerp.models.users.user_list_view_preference import UserListViewPreference

CALENDAR_PAGE_SIZE = 5
CALENDAR_VIEW_MODES = {"day", "week", "month", "year", "list"}
from .grouping import CALENDAR_COLORS, calendar_group_color, readable_calendar_groups


class CalendarDataviewRenderer(UnscheduledDataviewMixin, BaseDataviewRenderer):
    """Render permission-filtered records in calendar periods and unit pages."""

    template_name = "dataview/calendar/body.html"
    item_template_name = "dataview/calendar/item.html"
    reserved_query_params: ClassVar[set[str]] = {
        "calendar_page",
        "calendar_view_mode",
        "calendar_unit",
        "calendar_unit_offset",
        "calendar_color_field",
        "calendar_color_values",
        "calendar_color_preferred",
        "calendar_unscheduled_page",
        "unscheduled_q",
    }

    def get_context_data(self, pagination: Any) -> dict[str, Any]:
        """Provide the grid and operation URLs for its saved or signed layout."""
        context = super().get_context_data(pagination)
        context.update(self.build_context())
        context.update(self._unscheduled_context())
        context.update({
            "calendar_mode_url": self._operation_url("view-mode"),
            "calendar_dates_url": self._operation_url("dates"),
            "calendar_unit_url": self._operation_url("unit"),
        })
        return context

    def _operation_url(self, action: str) -> str:
        """Address saved layouts by preference ID and inline calendars by token."""
        kwargs: dict[str, int | str] = {
            "content_type_id": self.state.content_type_id,
            "action": action,
        }
        if self.state.preference.pk is not None:
            kwargs["preference_id"] = self.state.preference.pk
        return reverse("components_dataview_renderer_operation", kwargs=kwargs)

    @staticmethod
    def _period_preferences(state: DataviewState) -> QuerySet[UserListViewPreference]:
        """Find the viewer's own selection row, including their local share reference."""
        from bloomerp.models.users.user_list_view_preference import (
            UserListViewPreference,
        )

        return UserListViewPreference.objects.filter(
            user=state.request.user, content_type=state.content_type, selected=True,
        )

    def _view_mode(self) -> str:
        """Apply only the viewer's saved period over an inline calendar's default."""
        if self.state.preference.pk is None:
            options = self._period_preferences(self.state).values_list("options", flat=True).first() or {}
            calendar = options.get("calendar") or {}
            saved = calendar.get("calendar_view_mode", calendar.get("view_mode"))
            if isinstance(saved, str) and saved in CALENDAR_VIEW_MODES:
                return saved

        configured = str(getattr(self.options, "calendar_view_mode", "week"))
        return configured if configured in CALENDAR_VIEW_MODES else "week"

    def get_item_context(
        self,
        obj: Model,
        row_index: int,
        action_context: DataviewActionContext,
        *,
        placement: str = "",
    ) -> dict[str, Any] | None:
        """Use the current period's positioning to render one calendar occurrence."""
        calendar = self.build_context(paginate_events=False)
        mode = calendar["view_mode"]
        matches = []
        start_field = self.get_start_field(self.state.fields, self.options)
        if (
            placement in ("", "unscheduled")
            and start_field
            and self._unscheduled_queryset(start_field).filter(pk=obj.pk).exists()
        ):
            event = self._unscheduled_event(obj, start_field, calendar["end_field"])
            matches.append(("unscheduled", "", event))
        if mode == "month":
            segments = (
                segment
                for week in calendar["calendar_month_segments_by_week"].values()
                for segment in week
            )
        else:
            segments = iter(calendar["calendar_week_segments"])
        matches.extend(
            ("segment", "", segment) for segment in segments if segment["object"].pk == obj.pk
        )
        if mode != "month":
            matches.extend(
                ("event", unit, event)
                for unit, group in calendar["calendar_events_by_unit"].items()
                for event in group["events"]
                if event["object"].pk == obj.pk and (mode != "week" or not event["all_day"])
            )
        if not matches or (placement and len(matches) != 1):
            return None
        variant, unit, event = matches[0]
        expected = "unscheduled"
        if variant == "segment":
            expected = f"segment:{event['start_date'].isoformat()}:{event['start_column']}:{event['span']}:{event['lane']}"
        elif variant == "event":
            expected = f"event:{unit}:{event['start_ms']}:{event['end_ms']}"
        if placement and placement != expected:
            return None
        context = super().get_item_context(obj, row_index, action_context, placement=placement)
        if context is not None:
            context.update({
                "variant": variant,
                "event": {**event, "object": obj},
                "calendar_unit": unit,
                "calendar_view_mode": mode,
            })
        return context

    def build_context(self, *, paginate_events: bool = True) -> dict[str, Any]:
        """Build a shared period containing timed and independently configured date-only events."""
        date_start, date_end = self._date_fields()
        start_field = self.get_start_field(self.state.fields, self.options) or date_start
        end_field = self.get_end_field(self.state.fields, self.options) or date_end
        color_field = self._color_field()
        view_mode = self._view_mode()

        today = timezone.localdate()
        context: dict[str, Any] = {
            "start_field": start_field,
            "end_field": end_field,
            "calendar_start_date_field": date_start,
            "calendar_end_date_field": date_end,
            "color_field": color_field,
            "view_mode": view_mode,
            "calendar_view_modes": (
                ("day", _("Day")),
                ("week", _("Week")),
                ("month", _("Month")),
                ("year", _("Year")),
                ("list", _("List")),
            ),
            "calendar_events_by_unit": {},
            "calendar_date_range": None,
            "calendar_current_date": None,
            "calendar_today": today,
            "calendar_legend": [],
            "calendar_month_segments_by_week": {},
            "calendar_week_segments": [],
            "calendar_page_querystring": self.build_querystring(
                self.state.request,
                ("page", "calendar_view_mode", "calendar_unit", "calendar_unit_offset"),
            ),
        }
        if not start_field:
            return context

        try:
            page_offset = int(self.state.request.GET.get("calendar_page", 0))
        except (TypeError, ValueError):
            page_offset = 0

        period = self._period(view_mode, today, page_offset)
        current_date, start_date, end_date = period
        calendar_days = [
            start_date + timedelta(days=index)
            for index in range((end_date - start_date).days + 1)
        ]
        context.update({
            "calendar_current_date": current_date,
            "calendar_page_offset": page_offset,
            "calendar_date_range": {"start": start_date, "end": end_date},
            "calendar_hours": list(range(24)),
            "calendar_days": calendar_days,
            "calendar_day_units": [
                {"date": day, "key": day.isoformat()}
                for day in calendar_days
            ],
            "calendar_day_columns": [
                {
                    "date": day,
                    "hours": [
                        {"hour": hour, "key": f"{day.isoformat()}T{hour:02d}", **self._hour_create_values(day, hour)}
                        for hour in range(24)
                    ],
                }
                for day in calendar_days
            ],
            "calendar_months": [
                {
                    "date": date(current_date.year, month, 1),
                    "key": f"{current_date.year}-{month:02d}",
                }
                for month in range(1, 13)
            ],
        })
        if view_mode == "month":
            context["calendar_weeks"] = self.build_month_calendar_grid(start_date, end_date)

        queryset = self._filter_calendar_period(
            self.state.queryset,
            start_field,
            end_field,
            start_date,
            end_date,
        )
        events, legend = self._build_events(queryset, start_field, end_field, color_field, view_mode=view_mode)
        events_by_unit = self._group_events(events, view_mode, start_date, end_date)
        context["calendar_legend"] = legend
        context["calendar_events_by_unit"] = {
            key: {
                "events": value[:CALENDAR_PAGE_SIZE] if paginate_events else value,
                "total": len(value),
                "has_more": len(value) > CALENDAR_PAGE_SIZE,
            }
            for key, value in events_by_unit.items()
        }
        if view_mode == "month":
            context["calendar_month_segments_by_week"] = self._build_month_segments(
                events,
                context["calendar_weeks"],
            )
        elif view_mode == "week":
            context["calendar_week_segments"] = self._build_month_segments(
                [event for event in events if event["all_day"]],
                [[{"date": day} for day in calendar_days]],
            ).get(0, [])
        return context

    @staticmethod
    def _hour_create_values(day: date, hour: int) -> dict[str, str]:
        """Provide timezone-aware defaults for one clicked hour and its one-hour end."""
        start = timezone.make_aware(datetime.combine(day, time(hour)))
        end = datetime.fromtimestamp(start.timestamp() + 3600, tz=timezone.get_current_timezone())
        return {"create_start": start.isoformat(), "create_end": end.isoformat()}

    @classmethod
    def handle_action(cls, action: str, request: HttpRequest, state: DataviewState) -> HttpResponse:
        """Dispatch calendar paging, scheduling changes, and period preferences."""
        if action == "view-mode":
            return cls._update_view_mode(request, state)
        if action == "dates":
            return cls._update_dates(request, state)
        if action == "unscheduled" and request.method == "POST":
            return cls(state).unschedule_record()
        if action not in {"unit", "unscheduled"}:
            return super().handle_action(action, request, state)
        if request.method != "GET":
            return HttpResponse("Method not allowed", status=405)

        renderer = cls(state)
        if action == "unscheduled":
            return renderer.render_unscheduled(renderer._unscheduled_context())

        date_start, date_end = renderer._date_fields()
        start_field = cls.get_start_field(state.fields, state.options) or date_start
        end_field = cls.get_end_field(state.fields, state.options) or date_end
        color_field = renderer._color_field()
        unit = request.GET.get("calendar_unit", "")
        view_mode = request.GET.get("calendar_view_mode") or renderer._view_mode()
        try:
            offset = max(0, int(request.GET.get("calendar_unit_offset", CALENDAR_PAGE_SIZE)))
        except (TypeError, ValueError):
            return HttpResponse("Invalid calendar unit offset", status=400)
        if not start_field or view_mode not in CALENDAR_VIEW_MODES:
            return HttpResponse("Calendar is not configured", status=400)

        unit_queryset = renderer._filter_unit_queryset(state.queryset, start_field, unit, view_mode)
        group_period = bool(date_start and date_end) or view_mode in {"day", "week"}
        if group_period:
            try:
                unit_day = date.fromisoformat(unit + "-01" if view_mode == "year" else unit.split("T")[0])
                if view_mode == "year":
                    last_day = date(unit_day.year + 1, 1, 1) if unit_day.month == 12 else date(unit_day.year, unit_day.month + 1, 1)
                    last_day -= timedelta(days=1)
                else:
                    last_day = unit_day
                if "T" in unit and (len(unit.split("T")[1]) != 2 or not 0 <= int(unit.split("T")[1]) <= 23):
                    raise ValueError("Invalid hour")
                unit_queryset = renderer._filter_calendar_period(state.queryset, start_field, end_field, unit_day, last_day)
            except (ValueError, OverflowError):
                return HttpResponse("Invalid calendar unit", status=400)
        if unit_queryset is None:
            return HttpResponse("Invalid calendar unit", status=400)
        events, _legend = renderer._build_events(unit_queryset, start_field, end_field, color_field, view_mode=view_mode)
        if group_period:
            events = renderer._group_events(events, view_mode, unit_day, last_day).get(unit, [])
        page = events[offset:offset + CALENDAR_PAGE_SIZE]
        from bloomerp.components.objects.dataviews.dataview import (
            build_dataview_action_context,
        )

        return render(request, "dataview/calendar/events.html", {
            "dataview_item_template": renderer.item_template_name,
            "content_type_id": state.content_type.id,
            "events": page,
            "fields": state.render_fields,
            "object_actions": state.object_actions,
            "dataview_action_context": build_dataview_action_context(request, state),
            "preference": state.preference,
            "calendar_unit": unit,
            "calendar_unit_offset": offset,
            "calendar_next_unit_offset": offset + len(page),
            "calendar_has_more": offset + len(page) < len(events),
            "calendar_view_mode": view_mode,
            "calendar_unit_url": renderer._operation_url("unit"),
            "calendar_page_querystring": cls.build_querystring(
                request,
                ("page", "calendar_view_mode", "calendar_unit", "calendar_unit_offset"),
            ),
        })

    @classmethod
    def _update_view_mode(cls, request: HttpRequest, state: DataviewState) -> HttpResponse:
        """Save the period to the editable layout or the viewer's private preference."""
        if request.method != "POST":
            return HttpResponse("Method not allowed", status=405)
        preference = state.preference
        if preference.pk is not None and not PreferenceManager(request.user).can_manage(preference):
            return HttpResponse("Forbidden", status=403)
        try:
            payload = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            return HttpResponse("Invalid JSON payload", status=400)
        mode = payload.get("view_mode") if isinstance(payload, dict) else None
        if not isinstance(mode, str) or mode not in CALENDAR_VIEW_MODES:
            return HttpResponse("Invalid calendar view mode", status=400)
        if preference.pk is None:
            with transaction.atomic():
                owned = cls._period_preferences(state).select_for_update()
                preference = owned.first()
                if preference is None:
                    try:
                        PreferenceManager(request.user).get_or_create_selected(
                            type(state.preference), {"content_type_id": state.content_type_id},
                        )
                    except IntegrityError:
                        if not owned.exists():
                            raise
                    preference = owned.get()
                cls._save_view_mode(preference, mode)
        else:
            cls._save_view_mode(preference, mode)
        return JsonResponse({"view_mode": mode})

    @staticmethod
    def _save_view_mode(preference: UserListViewPreference, mode: str) -> None:
        """Update the calendar period while preserving the other preference options."""
        options = dict(preference.options or {})
        calendar_options = dict(options.get("calendar", {}))
        calendar_options.pop("view_mode", None)
        options["calendar"] = {**calendar_options, "calendar_view_mode": mode}
        preference.options = options
        preference.save(update_fields=["options"])

    @classmethod
    def _update_dates(cls, request: HttpRequest, state: DataviewState) -> HttpResponse:
        """Update configured calendar boundaries after keyboard, resize, or drop actions."""
        if request.method != "POST":
            return HttpResponse("Method not allowed", status=405)
        try:
            payload = json.loads(request.body)
        except (TypeError, ValueError, json.JSONDecodeError):
            return HttpResponse("Invalid JSON payload", status=400)

        updates = payload.get("updates") if isinstance(payload, dict) else None
        if not isinstance(updates, list) or not 1 <= len(updates) <= 100:
            return HttpResponse("Expected between 1 and 100 updates", status=400)

        renderer = cls(state)
        date_start, date_end = renderer._date_fields()
        start_field = cls.get_start_field(state.fields, state.options) or date_start
        end_field = cls.get_end_field(state.fields, state.options) or date_end
        if start_field is None:
            return HttpResponse("Calendar date field is not configured", status=400)

        fields_by_key = {"start_ms": start_field, "end_ms": end_field}
        requested_field_keys = {
            key
            for update in updates
            if isinstance(update, dict)
            for key in fields_by_key
            if key in update
        }
        if not requested_field_keys:
            return HttpResponse("No date values supplied", status=400)
        permission_manager = UserPolicyManager(request.user)
        if not permission_manager.has_global_permission(state.model, BloomerpPermission.CHANGE):
            return HttpResponse("Permission denied", status=403)
        object_ids = [str(update.get("object_id", "")) for update in updates if isinstance(update, dict)]
        if len(object_ids) != len(updates) or any(not object_id for object_id in object_ids):
            return HttpResponse("Every update requires an object ID", status=400)
        if len(set(object_ids)) != len(object_ids):
            return HttpResponse("Duplicate object IDs are not allowed", status=400)

        with transaction.atomic():
            objects = list(
                permission_manager.get_queryset(state.model, BloomerpPermission.CHANGE)
                .select_for_update()
                .filter(pk__in=object_ids)
            )
            objects_by_id = {str(obj.pk): obj for obj in objects}
            if set(objects_by_id) != set(object_ids):
                return HttpResponse("Permission denied", status=403)

            pending_saves = []
            for update in updates:
                obj = objects_by_id[str(update["object_id"])]
                fields = renderer._event_fields(obj, start_field, end_field)
                if fields is None:
                    return HttpResponse("Invalid calendar date range", status=400)
                event_start, event_end, exclusive = fields
                fields_by_key = {"start_ms": event_start, "end_ms": event_end}
                requested_fields = [fields_by_key[key] for key in fields_by_key if key in update]
                if not requested_fields or any(field is None for field in requested_fields):
                    return HttpResponse("Calendar date field is not configured", status=400)
                if any(
                    not GanttDataviewRenderer._field_is_editable(field)
                    or not permission_manager.has_access_to_object(obj, BloomerpPermission.CHANGE, fields=[field.field])
                    for field in requested_fields
                ):
                    return HttpResponse("Permission denied", status=403)
                changed_fields = []
                try:
                    for key, is_end in (("start_ms", False), ("end_ms", True)):
                        if key not in update:
                            continue
                        field = fields_by_key[key]
                        value = GanttDataviewRenderer._stored_date_value(
                            update[key], field, is_end=is_end,
                        )
                        if exclusive and is_end:
                            value += timedelta(days=1)
                        setattr(obj, field.field, value)
                        changed_fields.append(field.field)
                except (OverflowError, TypeError, ValueError):
                    return HttpResponse("Invalid date value", status=400)

                display_start = GanttDataviewRenderer._as_datetime(
                    getattr(obj, event_start.field, None)
                )
                display_end = (
                    GanttDataviewRenderer._as_datetime(
                        getattr(obj, event_end.field, None),
                        end_of_date=not exclusive and event_end.field_type == "DateField",
                    )
                    if event_end else None
                )
                if display_start is not None and display_end is not None and display_end <= display_start:
                    return HttpResponse("End must be after start", status=400)
                pending_saves.append((obj, list(dict.fromkeys(changed_fields)), event_start, event_end, exclusive))

            response_updates = []
            for obj, changed_fields, event_start, event_end, exclusive in pending_saves:
                obj.save(update_fields=changed_fields)
                display_start = GanttDataviewRenderer._as_datetime(
                    getattr(obj, event_start.field, None)
                )
                display_end = (
                    GanttDataviewRenderer._as_datetime(
                        getattr(obj, event_end.field, None),
                        end_of_date=not exclusive and event_end.field_type == "DateField",
                    )
                    if event_end else display_start
                )
                response_updates.append({
                    "object_id": str(obj.pk),
                    "start_ms": GanttDataviewRenderer._to_milliseconds(display_start),
                    "end_ms": GanttDataviewRenderer._to_milliseconds(display_end),
                })

        return JsonResponse({"status": "ok", "updates": response_updates})

    @classmethod
    def get_start_field(cls, dataview_fields, options):
        return cls.get_field_from_data_view_fields(
            dataview_fields, getattr(options, "start_field", None)
        )

    @classmethod
    def get_end_field(cls, dataview_fields, options):
        return cls.get_field_from_data_view_fields(
            dataview_fields, getattr(options, "end_field", None)
        )

    @classmethod
    def get_color_field(cls, dataview_fields, options):
        return cls.get_field_from_data_view_fields(
            dataview_fields, getattr(options, "color_grouping_field", None)
        )

    @staticmethod
    def _period(view_mode: str, today: date, page_offset: int) -> tuple[date, date, date]:
        if view_mode == "day":
            current = today + timedelta(days=page_offset)
            return current, current, current
        if view_mode == "week":
            current = today - timedelta(days=today.weekday()) + timedelta(weeks=page_offset)
            return current, current, current + timedelta(days=6)
        if view_mode in {"month", "list"}:
            year = today.year + (today.month - 1 + page_offset) // 12
            month = (today.month - 1 + page_offset) % 12 + 1
            current = date(year, month, 1)
            following = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
            return current, current, following - timedelta(days=1)
        current = date(today.year + page_offset, 1, 1)
        return current, current, date(current.year, 12, 31)

    @classmethod
    def _filter_period_queryset(
        cls,
        queryset: QuerySet,
        start_field: ApplicationField,
        end_field: ApplicationField | None,
        start_date: date,
        end_date: date,
    ) -> QuerySet:
        start_boundary = cls._field_boundary(start_field, start_date, start=False)
        end_boundary = cls._field_boundary(start_field, end_date, start=True)
        query = Q(**{f"{start_field.field}__gte": start_boundary, f"{start_field.field}__lt": end_boundary})
        if end_field:
            overlap_start = cls._field_boundary(end_field, start_date, start=False)
            query |= Q(**{
                f"{start_field.field}__lt": end_boundary,
                f"{end_field.field}__gte": overlap_start,
            })
        return queryset.filter(query).order_by(start_field.field, "pk")

    @classmethod
    def _filter_unit_queryset(
        cls,
        queryset: QuerySet,
        start_field: ApplicationField,
        unit: str,
        view_mode: str,
    ) -> QuerySet | None:
        try:
            if view_mode == "year":
                unit_date = datetime.strptime(unit, "%Y-%m").date()
                start = unit_date.replace(day=1)
                following = date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)
            elif view_mode in {"day", "week"} and "T" in unit:
                unit_datetime = datetime.strptime(unit, "%Y-%m-%dT%H")
                start = unit_datetime
                following = unit_datetime + timedelta(hours=1)
            else:
                start = datetime.strptime(unit, "%Y-%m-%d").date()
                following = start + timedelta(days=1)
        except ValueError:
            return None

        if start_field.field_type == "DateTimeField":
            if isinstance(start, date) and not isinstance(start, datetime):
                start = datetime.combine(start, time.min)
            if isinstance(following, date) and not isinstance(following, datetime):
                following = datetime.combine(following, time.min)
            current_timezone = timezone.get_current_timezone()
            if timezone.is_naive(start):
                start = timezone.make_aware(start, current_timezone)
            if timezone.is_naive(following):
                following = timezone.make_aware(following, current_timezone)
        elif isinstance(start, datetime):
            start = start.date()
            following = following.date()

        return queryset.filter(**{
            f"{start_field.field}__gte": start,
            f"{start_field.field}__lt": following,
        }).order_by(start_field.field, "pk")

    def _date_fields(self) -> tuple[ApplicationField | None, ApplicationField | None]:
        """Resolve the readable date-only range without relying on an all-day model flag."""
        start_name = getattr(self.options, "start_date_field", None)
        end_name = getattr(self.options, "end_date_field", None)
        stored = (self.state.preference.options or {}).get("calendar", {})
        if self.state.preference.pk and "start_date_field" not in stored and "end_date_field" not in stored:
            config = get_model_config(self.state.model)
            defaults = config.model_view_settings.default_dataviews if config and config.model_view_settings else []
            for configured in defaults:
                if configured.view_type == "calendar" and configured.name == self.state.preference.name:
                    start_name = start_name or getattr(configured, "start_date_field", None)
                    end_name = end_name or getattr(configured, "end_date_field", None)
                    break
        start = self.get_field_from_data_view_fields(self.state.fields, start_name)
        end = self.get_field_from_data_view_fields(self.state.fields, end_name)
        if not start or not end or start.field_type != "DateField" or end.field_type != "DateField":
            return None, None
        return start, end

    def _filter_calendar_period(
        self, queryset: QuerySet, start_field: ApplicationField,
        end_field: ApplicationField | None, start_date: date, end_date: date,
    ) -> QuerySet:
        """Include overlapping timed ranges and date-only ranges with exclusive ends."""
        primary = self._filter_period_queryset(queryset, start_field, end_field, start_date, end_date)
        date_start, date_end = self._date_fields()
        if not date_start or not date_end:
            return primary
        dates = Q(**{
            f"{date_start.field}__lt": end_date + timedelta(days=1),
            f"{date_end.field}__gt": start_date,
        })
        if start_field.field == date_start.field:
            return queryset.filter(dates).order_by(date_start.field, "pk")
        return queryset.filter(Q(pk__in=primary.values("pk")) | dates).order_by(start_field.field, "pk")

    def _event_fields(
        self, obj: Model, start_field: ApplicationField, end_field: ApplicationField | None,
    ) -> tuple[ApplicationField, ApplicationField | None, bool] | None:
        """Select one complete range per event and reject ambiguous or incomplete date-only data."""
        date_start, date_end = self._date_fields()
        if date_start and date_end:
            start = getattr(obj, date_start.field, None)
            end = getattr(obj, date_end.field, None)
            if start is not None or end is not None:
                if not isinstance(start, date) or isinstance(start, datetime) or not isinstance(end, date) or isinstance(end, datetime) or end <= start:
                    return None
                if start_field.field != date_start.field and (
                    getattr(obj, start_field.field, None) is not None
                    or (end_field and getattr(obj, end_field.field, None) is not None)
                ):
                    return None
                return date_start, date_end, True
        return start_field, end_field, bool(date_start and start_field.field == date_start.field)

    def _color_field(self) -> ApplicationField | None:
        """Resolve a transient grouping override only from the dataview's readable fields."""
        name = self.state.request.GET.get("calendar_color_field")
        if name:
            return self.get_field_from_data_view_fields(self.state.fields, name)
        return self.get_color_field(self.state.fields, self.options)

    def _color_relation(self, field: ApplicationField | None) -> Any:
        """Identify a concrete configured relation without treating scalar values as managers."""
        if field is None:
            return None
        try:
            model_field = self.state.model._meta.get_field(field.field)
        except (AttributeError, FieldDoesNotExist):
            return None
        return model_field if model_field.is_relation else None

    def _color_groups(self, obj: Model, field: ApplicationField | None) -> list[dict[str, str]]:
        """Return readable scalar or relation memberships, optionally narrowed to selected values."""
        if field is None:
            return []
        manager = UserPolicyManager(self.state.request.user)
        if not manager.has_access_to_object(obj, "view", fields=[field.field]):
            return []
        relation = self._color_relation(field)
        selected = self.state.request.GET.get("calendar_color_values")
        allowed = {value.strip() for value in selected.split(",")} if selected is not None else None
        if relation is None:
            label = self._display_value(obj, field)
            groups = [{
                "value": label, "label": label,
                "color_classes": calendar_group_color(label),
            }]
        else:
            value = getattr(obj, field.field, None)
            if relation.many_to_many or relation.one_to_many:
                members = getattr(obj, "_calendar_color_memberships", None)
                if members is None:
                    members = (
                        readable_calendar_groups(self.state.request.user, relation.related_model)
                        .filter(pk__in=value.all().values("pk"))
                        if value is not None else []
                    )
            else:
                members = (
                    [value] if value is not None
                    and readable_calendar_groups(self.state.request.user, relation.related_model)
                    .filter(pk=value.pk).exists() else []
                )
            groups = [{
                "value": str(item.pk), "label": str(item),
                "color_classes": calendar_group_color(str(item.pk), relation=True),
            } for item in members]
        groups = [group for group in groups if allowed is None or group["value"] in allowed]
        preferred = self.state.request.GET.get("calendar_color_preferred")
        return sorted(groups, key=partial(calendar_group_order, preferred=preferred))

    def _build_events(
        self,
        objects: Iterable[Model],
        start_field: ApplicationField,
        end_field: ApplicationField | None,
        color_field: ApplicationField | None,
        *,
        view_mode: str | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        """Build calendar items with readable color memberships and their configured times."""
        raw_events = []
        legend_groups: dict[str, dict[str, str]] = {}
        if isinstance(objects, QuerySet):
            objects = objects.distinct()
            relation = self._color_relation(color_field)
            if relation is not None and (relation.many_to_many or relation.one_to_many):
                objects = objects.prefetch_related(Prefetch(
                    color_field.field,
                    queryset=readable_calendar_groups(self.state.request.user, relation.related_model),
                    to_attr="_calendar_color_memberships",
                ))
        seen: set[str] = set()
        for obj in objects:
            if str(obj.pk) in seen:
                continue
            seen.add(str(obj.pk))
            fields = self._event_fields(obj, start_field, end_field)
            if fields is None:
                continue
            event_start, event_end, exclusive = fields
            if not UserPolicyManager(self.state.request.user).has_access_to_object(
                obj, BloomerpPermission.VIEW,
                fields=[event_start.field] + ([event_end.field] if event_end else []),
            ):
                continue
            start_value = getattr(obj, event_start.field, None)
            if not isinstance(start_value, (date, datetime)):
                continue
            end_value = getattr(obj, event_end.field, None) if event_end else None
            has_end_time = isinstance(end_value, datetime)
            if not isinstance(end_value, (date, datetime)):
                end_value = start_value
            if exclusive:
                end_value -= timedelta(days=1)
            if isinstance(start_value, datetime) and timezone.is_aware(start_value):
                start_value = timezone.localtime(start_value)
            if isinstance(end_value, datetime) and timezone.is_aware(end_value):
                end_value = timezone.localtime(end_value)
            groups = self._color_groups(obj, color_field)
            for group in groups:
                legend_groups[group["value"]] = group
            raw_events.append((obj, start_value, end_value, has_end_time, groups, event_start, event_end))

        events = []
        for obj, start_value, end_value, has_end_time, groups, event_start, event_end in raw_events:
            can_edit_start, can_edit_end = self._edit_permissions_for_object(
                obj,
                event_start,
                event_end,
            )
            start_datetime = GanttDataviewRenderer._as_datetime(start_value)
            end_datetime = GanttDataviewRenderer._as_datetime(
                end_value,
                end_of_date=bool(event_end and event_end.field_type == "DateField"),
            )
            if end_datetime is None:
                end_datetime = start_datetime
            duration_minutes = max(
                15,
                int((end_datetime - start_datetime).total_seconds() / 60)
                if start_datetime and end_datetime else 60,
            )
            events.append({
                "object": obj,
                "start": start_value,
                "end": end_value,
                "start_date": self._as_date(start_value),
                "end_date": self._as_date(end_value),
                "start_time": start_value.time() if isinstance(start_value, datetime) else None,
                "end_time": end_value.time() if has_end_time else None,
                "all_day": not isinstance(start_value, datetime),
                "color_group": groups[0]["label"] if groups else "",
                "color_classes": groups[0]["color_classes"] if groups else CALENDAR_COLORS[0],
                "color_groups": groups,
                "additional_color_groups": groups[1:],
                "start_ms": GanttDataviewRenderer._to_milliseconds(start_datetime),
                "end_ms": GanttDataviewRenderer._to_milliseconds(end_datetime),
                "start_minute": start_value.minute if isinstance(start_value, datetime) else 0,
                "duration_minutes": duration_minutes,
                "can_edit_start": can_edit_start,
                "can_edit_end": can_edit_end,
                "can_move": can_edit_start and (event_end is None or can_edit_end),
                "can_unschedule": (
                    can_edit_start and (event_end is None or can_edit_end)
                    and self.scheduling_dates_are_optional(
                        *((event_start, event_end) if event_end else (event_start,)),
                    )
                ),
            })
        legend = list(legend_groups.values())
        if (view_mode or self.options.calendar_view_mode) in {"day", "week"}:
            events = self._position_timed_events(self._split_timed_events(events))
        return events, legend

    @staticmethod
    def _position_timed_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Allocate columns using the actual intervals of each day's event segments."""
        positioned = [dict(event) for event in events]
        by_day: defaultdict[date, list[dict[str, Any]]] = defaultdict(list)
        for event in positioned:
            if not event["all_day"]:
                by_day[event["start_date"]].append(event)

        def event_order(event: dict[str, Any]) -> tuple[float, float, str]:
            """Order simultaneous starts deterministically, placing longer ranges first."""
            return event["timed_start"], -event["timed_end"], str(event["object"].pk)

        def leave_room_for_next_card(event: dict[str, Any], next_start: float) -> None:
            """Shrink a card's display minimum when it would cover the next card."""
            available = max(0, (next_start - event["timed_start"]) / 60)
            if event["display_duration_minutes"] > available:
                event["display_duration_minutes"] = event["duration_minutes"] or available

        for day_events in by_day.values():
            lanes: list[dict[str, Any]] = []
            cluster: list[dict[str, Any]] = []
            cluster_end = float("-inf")
            for event in sorted(day_events, key=event_order):
                start, end = event["timed_start"], event["timed_end"]
                # At 5rem per hour, the two-line card's 2.75rem height spans 33 minutes.
                event["display_duration_minutes"] = max(33, event["duration_minutes"])
                if cluster and start >= cluster_end:
                    for member in cluster:
                        member["timed_columns"] = len(lanes)
                        leave_room_for_next_card(member, start)
                    lanes = []
                    cluster = []
                    cluster_end = end
                lane = next(
                    (index for index, previous in enumerate(lanes) if previous["timed_end"] <= start),
                    len(lanes),
                )
                if lane == len(lanes):
                    lanes.append(event)
                else:
                    leave_room_for_next_card(lanes[lane], start)
                    lanes[lane] = event
                event["timed_column"] = lane
                cluster.append(event)
                cluster_end = max(cluster_end, end)
            for member in cluster:
                member["timed_columns"] = len(lanes)
        return positioned

    @staticmethod
    def _split_timed_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Show overnight timed ranges on each day while preserving their original edit timestamps."""
        result = []
        for event in events:
            if event["all_day"]:
                result.append(event)
                continue
            current = GanttDataviewRenderer._as_datetime(event["start"])
            end = GanttDataviewRenderer._as_datetime(event["end"])
            if not isinstance(event["end"], datetime) or end.timestamp() <= current.timestamp():
                result.append({
                    **event,
                    "timed_start": current.timestamp(),
                    "timed_end": current.timestamp(),
                    "duration_minutes": 0,
                })
                continue
            while current.timestamp() < end.timestamp():
                following = datetime.combine(current.date() + timedelta(days=1), time.min, tzinfo=current.tzinfo)
                segment_end = end if end.timestamp() <= following.timestamp() else following
                duration = (segment_end - current).total_seconds() / 60
                result.append({
                    **event,
                    "start_date": current.date(),
                    "end_date": (segment_end - timedelta(microseconds=1)).date(),
                    "start_time": current.time(),
                    "start_minute": current.minute + (current.second + current.microsecond / 1_000_000) / 60,
                    "duration_minutes": max(0, duration),
                    "timed_start": current.timestamp(),
                    "timed_end": segment_end.timestamp(),
                })
                current = segment_end
        return result

    def _unscheduled_queryset(self, start_field: ApplicationField) -> QuerySet:
        """Find unscheduled records whose start field is visible to the viewer."""
        queryset = self.state.queryset.filter(**{f"{start_field.field}__isnull": True})
        date_start, date_end = self._date_fields()
        if date_start and date_end:
            queryset = queryset.filter(**{f"{date_start.field}__isnull": True})
        manager = UserPolicyManager(self.state.request.user)
        return manager.annotate_field_permissions(
            queryset, [start_field], BloomerpPermission.VIEW,
        ).filter(**{field_access_annotation_name(start_field): True})

    def get_unschedule_fields(self, obj: Model) -> tuple[ApplicationField, ...]:
        """Identify the record's active timed or all-day range for unscheduling."""
        start_field = self.get_start_field(self.state.fields, self.options)
        if start_field is None:
            return ()
        _, date_end = self._date_fields()
        end_field = self.get_end_field(self.state.fields, self.options) or date_end
        fields = self._event_fields(obj, start_field, end_field)
        if fields is None:
            return ()
        event_start, event_end, _ = fields
        return (event_start, event_end) if event_end else (event_start,)

    def _unscheduled_context(self) -> dict[str, Any]:
        """Search and page records that have no visible calendar placement."""
        start_field = self.get_start_field(self.state.fields, self.options)
        # A date-only fallback cannot distinguish unscheduled rows from hidden timed ranges.
        if not start_field:
            return {}
        _, date_end = self._date_fields()
        end_field = self.get_end_field(self.state.fields, self.options) or date_end
        page = self.paginate_unscheduled(
            self._unscheduled_queryset(start_field), 25, "calendar_unscheduled_page",
        )
        return self.unscheduled_context(
            page,
            [self._unscheduled_event(obj, start_field, end_field) for obj in page],
            "calendar_unscheduled_page",
        )

    def _unscheduled_event(
        self,
        obj: Model,
        start_field: ApplicationField,
        end_field: ApplicationField | None,
    ) -> dict[str, Any]:
        """Preserve the record's date edit permissions in the sidebar item."""
        can_edit_start, can_edit_end = self._edit_permissions_for_object(obj, start_field, end_field)
        return {
            "object": obj,
            "can_edit_start": can_edit_start,
            "can_edit_end": can_edit_end if end_field else True,
        }

    def _edit_permissions_for_object(
        self,
        obj,
        start_field: ApplicationField,
        end_field: ApplicationField | None,
    ) -> tuple[bool, bool]:
        if not UserPolicyManager(self.state.request.user).has_access_to_object(obj, BloomerpPermission.CHANGE):
            return False, False
        can_edit_start = (
            GanttDataviewRenderer._field_is_editable(start_field)
            and UserPolicyManager(self.state.request.user).has_field_permission(start_field, BloomerpPermission.CHANGE)
        )
        can_edit_end = bool(
            end_field
            and GanttDataviewRenderer._field_is_editable(end_field)
            and UserPolicyManager(self.state.request.user).has_field_permission(end_field, BloomerpPermission.CHANGE)
        )
        return can_edit_start, can_edit_end

    @staticmethod
    def _build_month_segments(
        events: list[dict[str, Any]],
        weeks: list[list[dict[str, Any]]],
    ) -> dict[int, list[dict[str, Any]]]:
        """Split ranges only at week boundaries and allocate non-overlapping lanes."""
        result = {}
        for week_index, week in enumerate(weeks):
            week_start = week[0]["date"]
            week_end = week[-1]["date"]
            lanes: list[date] = []
            segments = []
            matching = sorted(
                (
                    event for event in events
                    if event["start_date"] <= week_end and event["end_date"] >= week_start
                ),
                key=lambda event: (event["start_date"], event["end_date"], str(event["object"].pk)),
            )
            for event in matching:
                segment_start = max(event["start_date"], week_start)
                segment_end = min(event["end_date"], week_end)
                lane = next(
                    (index for index, occupied_until in enumerate(lanes) if occupied_until < segment_start),
                    len(lanes),
                )
                if lane == len(lanes):
                    lanes.append(segment_end)
                else:
                    lanes[lane] = segment_end
                segments.append({
                    **event,
                    "start_column": (segment_start - week_start).days + 1,
                    "span": (segment_end - segment_start).days + 1,
                    "lane": lane,
                })
            result[week_index] = segments
        return result

    @classmethod
    def _group_events(
        cls,
        events: Iterable[dict[str, Any]],
        view_mode: str,
        period_start: date,
        period_end: date,
    ) -> dict[str, list[dict[str, Any]]]:
        """Group visible ranges by calendar unit without including dates beyond their displayed ends."""
        grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in events:
            start_date = max(event["start_date"], period_start)
            end_date = min(event["end_date"], period_end)
            if start_date > end_date:
                continue
            if view_mode == "year":
                current = date(start_date.year, start_date.month, 1)
                last = date(end_date.year, end_date.month, 1)
                while current <= last:
                    grouped[current.strftime("%Y-%m")].append(event)
                    current = date(current.year + 1, 1, 1) if current.month == 12 else date(current.year, current.month + 1, 1)
                continue
            if view_mode in {"day", "week"} and not event["all_day"]:
                grouped[f"{event['start_date'].isoformat()}T{event['start_time'].hour:02d}"].append(event)
                continue
            current = start_date
            while current <= end_date:
                grouped[current.isoformat()].append(event)
                current += timedelta(days=1)
        return dict(grouped)

    @staticmethod
    def _display_value(obj, field: ApplicationField | None) -> str:
        if field is None:
            return ""
        display_method = getattr(obj, f"get_{field.field}_display", None)
        value = display_method() if callable(display_method) else getattr(obj, field.field, None)
        return "Unassigned" if value in (None, "") else str(value)

    @staticmethod
    def _as_date(value: date | datetime) -> date:
        if isinstance(value, datetime):
            return timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
        return value

    @staticmethod
    def _field_boundary(field: ApplicationField, value: date, *, start: bool):
        if field.field_type != "DateTimeField":
            return value + timedelta(days=1) if start else value
        boundary = datetime.combine(value + (timedelta(days=1) if start else timedelta()), time.min)
        return timezone.make_aware(boundary, timezone.get_current_timezone())

    @staticmethod
    def build_month_calendar_grid(start_date: date, end_date: date) -> list[list[dict[str, Any]]]:
        """Build month cells with timezone-aware full-day defaults for modal creation."""
        grid_start = start_date - timedelta(days=start_date.weekday())
        grid_end = end_date + timedelta(days=6 - end_date.weekday())
        weeks = []
        current = grid_start
        while current <= grid_end:
            week = []
            for _day_index in range(7):
                week.append({
                    "date": current,
                    "key": current.isoformat(),
                    "is_current_month": start_date <= current <= end_date,
                    "is_today": current == timezone.localdate(),
                    "create_start": timezone.make_aware(datetime.combine(current, time.min)).isoformat(),
                    "create_end": timezone.make_aware(datetime.combine(current + timedelta(days=1), time.min)).isoformat(),
                })
                current += timedelta(days=1)
            weeks.append(week)
        return weeks


def calendar_group_order(group: dict[str, str], *, preferred: str | None) -> tuple[bool, str]:
    """Prefer the requested membership while ordering all remaining IDs deterministically."""
    return group["value"] != preferred, group["value"]
