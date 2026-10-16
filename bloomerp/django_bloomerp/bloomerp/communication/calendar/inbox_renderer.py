"""Adapt the standard calendar renderer to shared meetings with two date representations."""

from collections.abc import Iterable
from copy import copy
from datetime import date, datetime, time, timedelta
from typing import Any

from django.db.models import Q, QuerySet
from django.utils import timezone

from bloomerp.dataviews.calendar.renderer import CalendarDataviewRenderer
from bloomerp.dataviews.definition import DataviewState
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.permissions.manager import UserPolicyManager


class InboxCalendarRenderer(CalendarDataviewRenderer):
    """Reuse calendar navigation, grouping, paging, and details for an Inbox scope."""

    def __init__(self, state: DataviewState) -> None:
        """Cache the standard state and policy manager for row-specific date checks."""
        super().__init__(state)
        self.permission_manager = UserPolicyManager(state.request.user)

    @classmethod
    def _filter_period_queryset(
        cls,
        queryset: QuerySet[CalendarEvent],
        start_field: ApplicationField,
        end_field: ApplicationField | None,
        start_date: date,
        end_date: date,
    ) -> QuerySet[CalendarEvent]:
        """Include overlapping timed and date-only meetings with exclusive ends."""
        start = timezone.make_aware(datetime.combine(start_date, time.min))
        following_date = end_date + timedelta(days=1)
        end = timezone.make_aware(datetime.combine(following_date, time.min))
        return queryset.filter(
            Q(all_day=False, start__lt=end, end__gt=start)
            | Q(all_day=True, start_date__lt=following_date, end_date__gt=start_date)
        ).order_by("start_date", "start", "pk")

    @staticmethod
    def unit_period(unit: str, view_mode: str) -> tuple[date, date]:
        """Return the inclusive date period represented by a standard calendar unit."""
        if view_mode == "year":
            start = date.fromisoformat(unit + "-01")
            following = (
                date(start.year + 1, 1, 1)
                if start.month == 12
                else date(start.year, start.month + 1, 1)
            )
            return start, following - timedelta(days=1)
        if view_mode in {"day", "week"} and "T" in unit:
            day_text, hour_text = unit.split("T")
            if (
                len(hour_text) != 2
                or not hour_text.isdigit()
                or not 0 <= int(hour_text) <= 23
            ):
                raise ValueError("Invalid calendar hour.")
            day = date.fromisoformat(day_text)
        else:
            day = date.fromisoformat(unit)
        return day, day

    @classmethod
    def _filter_unit_queryset(
        cls,
        queryset: QuerySet[CalendarEvent],
        start_field: ApplicationField,
        unit: str,
        view_mode: str,
    ) -> QuerySet[CalendarEvent] | None:
        """Reuse period overlap semantics for scoped load-more requests."""
        try:
            start, end = cls.unit_period(unit, view_mode)
        except ValueError:
            return None
        return cls._filter_period_queryset(queryset, start_field, None, start, end)

    def _build_events(
        self,
        objects: Iterable[CalendarEvent],
        start_field: ApplicationField,
        end_field: ApplicationField | None,
        color_field: ApplicationField | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        """Render only readable dates, keeping all-day ends exclusive and timed hours local."""
        events: list[dict[str, Any]] = []
        fields = {
            field.field: field for field, _ in self.state.fields.accessible_fields
        }
        for obj in objects:
            if not self.permission_manager.has_access_to_object(
                obj, "view", fields=["inboxes", "all_day", "cancelled"]
            ):
                continue
            names = ("start_date", "end_date") if obj.all_day else ("start", "end")
            if any(name not in fields for name in names):
                continue
            if not self.permission_manager.has_access_to_object(
                obj, "view", fields=list(names)
            ):
                continue
            if obj.all_day:
                displayed = copy(obj)
                displayed.end_date = obj.end_date - timedelta(days=1)
                built, _ = super()._build_events(
                    [displayed], fields[names[0]], fields[names[1]], None
                )
                for event in built:
                    event["object"] = obj
                events.extend(built)
                continue
            start, end = timezone.localtime(obj.start), timezone.localtime(obj.end)
            # Week/day grids need a timed segment on each day, not an all-day bar.
            split_days = self.options.view_mode in {"day", "week"}
            current = start
            while current < end:
                next_midnight = timezone.make_aware(
                    datetime.combine(current.date() + timedelta(days=1), time.min)
                )
                segment_end = min(end, next_midnight) if split_days else end
                displayed = copy(obj)
                displayed.start, displayed.end = current, segment_end
                built, _ = super()._build_events(
                    [displayed], fields[names[0]], fields[names[1]], None
                )
                for event in built:
                    event["object"] = obj
                    event["all_day"] = False
                    if segment_end.time() == time.min:
                        event["end_date"] = segment_end.date() - timedelta(days=1)
                events.extend(built)
                if not split_days:
                    break
                current = segment_end
        return events, []

    def _build_unscheduled_events(
        self,
        start_field: ApplicationField,
        end_field: ApplicationField | None,
    ) -> list[dict[str, Any]]:
        """All-day meetings have date ranges and must never enter an unscheduled tray."""
        return []

    def _edit_permissions_for_object(
        self,
        obj: CalendarEvent,
        start_field: ApplicationField,
        end_field: ApplicationField | None,
    ) -> tuple[bool, bool]:
        """Keep this calendar read-only so scheduling authority stays in event actions."""
        return False, False
