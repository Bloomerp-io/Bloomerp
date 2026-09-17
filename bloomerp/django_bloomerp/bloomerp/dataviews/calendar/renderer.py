from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable

from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone

from bloomerp.models.application_field import ApplicationField
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager

from ..definition import BaseDataviewRenderer, DataviewRenderState
from ..gant.renderer import GanttDataviewRenderer


CALENDAR_PAGE_SIZE = 5
CALENDAR_VIEW_MODES = {"day", "week", "month", "year", "list"}
CALENDAR_COLORS = (
    "bg-primary-100 text-primary-800 border-primary-200",
    "bg-secondary-100 text-secondary-800 border-secondary-200",
    "bg-success-light text-success-dark border-success-light",
    "bg-warning-light text-warning-dark border-warning-light",
    "bg-danger-light text-danger-dark border-danger-light",
    "bg-base text-dark border-gray-200",
)


class CalendarDataviewRenderer(BaseDataviewRenderer):
    """Render permission-filtered records in calendar periods and unit pages."""

    template_name = "cotton/features/dataviews/calendar.html"
    reserved_query_params = {
        "calendar_page",
        "calendar_view_mode",
        "calendar_unit",
        "calendar_unit_offset",
    }

    def get_context_data(self, pagination) -> dict[str, Any]:
        context = super().get_context_data(pagination)
        context.update(self.build_context())
        return context

    def build_context(self) -> dict[str, Any]:
        start_field = self.get_start_field(self.state.fields, self.options)
        end_field = self.get_end_field(self.state.fields, self.options)
        color_field = self.get_color_field(self.state.fields, self.options)
        configured_mode = str(getattr(self.options, "view_mode", "week"))
        view_mode = configured_mode
        if view_mode not in CALENDAR_VIEW_MODES:
            view_mode = "week"

        today = timezone.localdate()
        context: dict[str, Any] = {
            "start_field": start_field,
            "end_field": end_field,
            "color_field": color_field,
            "view_mode": view_mode,
            "calendar_view_modes": (
                ("day", "Day"),
                ("week", "Week"),
                ("month", "Month"),
                ("year", "Year"),
                ("list", "List"),
            ),
            "calendar_events_by_unit": {},
            "calendar_date_range": None,
            "calendar_current_date": None,
            "calendar_today": today,
            "calendar_legend": [],
            "calendar_month_segments_by_week": {},
            "calendar_week_segments": [],
            "calendar_unscheduled_events": [],
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
                        {"hour": hour, "key": f"{day.isoformat()}T{hour:02d}"}
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

        queryset = self._filter_period_queryset(
            self.state.queryset,
            start_field,
            end_field,
            start_date,
            end_date,
        )
        events, legend = self._build_events(queryset, start_field, end_field, color_field)
        events_by_unit = self._group_events(events, view_mode, start_date, end_date)
        context["calendar_legend"] = legend
        context["calendar_events_by_unit"] = {
            key: {
                "events": value[:CALENDAR_PAGE_SIZE],
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
        context["calendar_unscheduled_events"] = self._build_unscheduled_events(
            start_field,
            end_field,
        )
        return context

    @classmethod
    def handle_action(cls, action: str, request: HttpRequest, state) -> HttpResponse:
        if action == "dates":
            return cls._update_dates(request, state)
        if action != "unit":
            return super().handle_action(action, request, state)
        if request.method != "GET":
            return HttpResponse("Method not allowed", status=405)

        start_field = cls.get_start_field(state.dataview_fields, state.dataview_options)
        end_field = cls.get_end_field(state.dataview_fields, state.dataview_options)
        color_field = cls.get_color_field(state.dataview_fields, state.dataview_options)
        unit = request.GET.get("calendar_unit", "")
        view_mode = request.GET.get("calendar_view_mode") or str(
            getattr(state.dataview_options, "view_mode", "week")
        )
        try:
            offset = max(0, int(request.GET.get("calendar_unit_offset", CALENDAR_PAGE_SIZE)))
        except (TypeError, ValueError):
            return HttpResponse("Invalid calendar unit offset", status=400)
        if not start_field or view_mode not in CALENDAR_VIEW_MODES:
            return HttpResponse("Calendar is not configured", status=400)

        renderer = cls(DataviewRenderState(
            request=request,
            content_type_id=state.content_type.id,
            content_type=state.content_type,
            model=state.model,
            preference=state.preference,
            queryset=state.queryset,
            fields=state.dataview_fields,
            render_fields=state.dataview_render_fields,
            avatar_field=state.avatar_field,
            options=state.dataview_options,
        ))
        unit_queryset = renderer._filter_unit_queryset(state.queryset, start_field, unit, view_mode)
        if unit_queryset is None:
            return HttpResponse("Invalid calendar unit", status=400)
        events, _legend = renderer._build_events(unit_queryset, start_field, end_field, color_field)
        page = events[offset:offset + CALENDAR_PAGE_SIZE]
        return render(request, "components/objects/dataview_calendar_events.html", {
            "content_type_id": state.content_type.id,
            "events": page,
            "fields": state.dataview_render_fields,
            "preference": state.preference,
            "calendar_unit": unit,
            "calendar_unit_offset": offset,
            "calendar_next_unit_offset": offset + len(page),
            "calendar_has_more": offset + len(page) < len(events),
            "calendar_view_mode": view_mode,
            "calendar_page_querystring": cls.build_querystring(
                request,
                ("page", "calendar_view_mode", "calendar_unit", "calendar_unit_offset"),
            ),
        })

    @classmethod
    def _update_dates(cls, request: HttpRequest, state) -> HttpResponse:
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

        start_field = cls.get_start_field(state.dataview_fields, state.dataview_options)
        end_field = cls.get_end_field(state.dataview_fields, state.dataview_options)
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
        if any(fields_by_key[key] is None for key in requested_field_keys):
            return HttpResponse("Calendar end field is not configured", status=400)

        permission_manager = UserPolicyManager(request.user)
        if not permission_manager.has_global_permission(state.model, BloomerpPermission.CHANGE):
            return HttpResponse("Permission denied", status=403)
        if any(
            not GanttDataviewRenderer._field_is_editable(fields_by_key[key])
            or not permission_manager.has_field_permission(fields_by_key[key], BloomerpPermission.CHANGE)
            for key in requested_field_keys
        ):
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
                changed_fields = []
                try:
                    for key, is_end in (("start_ms", False), ("end_ms", True)):
                        if key not in update:
                            continue
                        field = fields_by_key[key]
                        setattr(
                            obj,
                            field.field,
                            GanttDataviewRenderer._stored_date_value(
                                update[key],
                                field,
                                is_end=is_end,
                            ),
                        )
                        changed_fields.append(field.field)
                except (OverflowError, TypeError, ValueError):
                    return HttpResponse("Invalid date value", status=400)

                display_start = GanttDataviewRenderer._as_datetime(
                    getattr(obj, start_field.field, None)
                )
                display_end = (
                    GanttDataviewRenderer._as_datetime(
                        getattr(obj, end_field.field, None),
                        end_of_date=end_field.field_type == "DateField",
                    )
                    if end_field else None
                )
                if display_start is not None and display_end is not None and display_end <= display_start:
                    return HttpResponse("End must be after start", status=400)
                pending_saves.append((obj, list(dict.fromkeys(changed_fields))))

            response_updates = []
            for obj, changed_fields in pending_saves:
                obj.save(update_fields=changed_fields)
                display_start = GanttDataviewRenderer._as_datetime(
                    getattr(obj, start_field.field, None)
                )
                display_end = (
                    GanttDataviewRenderer._as_datetime(
                        getattr(obj, end_field.field, None),
                        end_of_date=end_field.field_type == "DateField",
                    )
                    if end_field else display_start
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
            dataview_fields, getattr(options, "start_field_id", None)
        )

    @classmethod
    def get_end_field(cls, dataview_fields, options):
        return cls.get_field_from_data_view_fields(
            dataview_fields, getattr(options, "end_field_id", None)
        )

    @classmethod
    def get_color_field(cls, dataview_fields, options):
        return cls.get_field_from_data_view_fields(
            dataview_fields, getattr(options, "color_grouping_field_id", None)
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

    def _build_events(
        self,
        objects: Iterable,
        start_field: ApplicationField,
        end_field: ApplicationField | None,
        color_field: ApplicationField | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        raw_events = []
        group_labels: list[str] = []
        for obj in objects:
            start_value = getattr(obj, start_field.field, None)
            if not isinstance(start_value, (date, datetime)):
                continue
            end_value = getattr(obj, end_field.field, None) if end_field else None
            if not isinstance(end_value, (date, datetime)):
                end_value = start_value
            group_label = self._display_value(obj, color_field) if color_field else ""
            if group_label not in group_labels:
                group_labels.append(group_label)
            raw_events.append((obj, start_value, end_value, group_label))

        color_by_group = {
            label: CALENDAR_COLORS[
                sum((index + 1) * ord(character) for index, character in enumerate(label))
                % len(CALENDAR_COLORS)
            ]
            for label in group_labels
        }
        events = []
        for obj, start_value, end_value, group_label in raw_events:
            can_edit_start, can_edit_end = self._edit_permissions_for_object(
                obj,
                start_field,
                end_field,
            )
            start_datetime = GanttDataviewRenderer._as_datetime(start_value)
            end_datetime = GanttDataviewRenderer._as_datetime(
                end_value,
                end_of_date=bool(end_field and end_field.field_type == "DateField"),
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
                "end_time": end_value.time() if isinstance(end_value, datetime) else None,
                "all_day": not isinstance(start_value, datetime) or (
                    self._as_date(end_value) > self._as_date(start_value)
                ),
                "color_group": group_label,
                "color_classes": color_by_group.get(group_label, CALENDAR_COLORS[0]),
                "start_ms": GanttDataviewRenderer._to_milliseconds(start_datetime),
                "end_ms": GanttDataviewRenderer._to_milliseconds(end_datetime),
                "start_minute": start_value.minute if isinstance(start_value, datetime) else 0,
                "duration_minutes": duration_minutes,
                "can_edit_start": can_edit_start,
                "can_edit_end": can_edit_end,
                "can_move": can_edit_start and (end_field is None or can_edit_end),
            })
        legend = [
            {"label": label or "Unassigned", "color_classes": color_by_group[label]}
            for label in group_labels
        ] if color_field else []
        return events, legend

    def _build_unscheduled_events(
        self,
        start_field: ApplicationField,
        end_field: ApplicationField | None,
    ) -> list[dict[str, Any]]:
        objects = self.state.queryset.filter(**{f"{start_field.field}__isnull": True})[:25]
        result = []
        for obj in objects:
            can_edit_start, can_edit_end = self._edit_permissions_for_object(
                obj,
                start_field,
                end_field,
            )
            result.append({
                "object": obj,
                "can_edit_start": can_edit_start,
                "can_edit_end": can_edit_end if end_field else True,
            })
        return result

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
        grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in events:
            start_date = max(event["start_date"], period_start)
            end_date = min(event["end_date"], period_end)
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
        grid_start = start_date - timedelta(days=start_date.weekday())
        grid_end = end_date + timedelta(days=6 - end_date.weekday())
        weeks = []
        current = grid_start
        while current <= grid_end:
            week = []
            for _ in range(7):
                week.append({
                    "date": current,
                    "key": current.isoformat(),
                    "is_current_month": start_date <= current <= end_date,
                    "is_today": current == timezone.localdate(),
                })
                current += timedelta(days=1)
            weeks.append(week)
        return weeks
