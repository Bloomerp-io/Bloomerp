from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from .base import BaseDataviewRenderer


class CalendarDataviewRenderer(BaseDataviewRenderer):
    template_name = "cotton/ui/data_view/calendar.html"
    reserved_query_params = {"calendar_page"}

    def get_context_data(self, pagination) -> dict:
        context = super().get_context_data(pagination)
        context.update(self.build_context())
        return context

    def build_context(self) -> dict:
        queryset = self.state.queryset
        request = self.state.request
        start_field = self.get_start_field(self.state.fields, self.options)
        end_field = self.get_end_field(self.state.fields, self.options)
        view_mode = getattr(self.options, "view_mode", "week")
        today = date.today()

        context = {
            "start_field": start_field,
            "end_field": end_field,
            "view_mode": view_mode,
            "calendar_events": [],
            "calendar_date_range": None,
            "calendar_current_date": None,
            "calendar_today": today,
        }

        if not start_field:
            return context

        field_name = start_field.field

        try:
            page_offset = int(request.GET.get("calendar_page", 0))
        except ValueError:
            page_offset = 0

        if view_mode == "day":
            current_date = today + timedelta(days=page_offset)
            start_date = current_date
            end_date = current_date
            context["calendar_hours"] = list(range(0, 24))
        elif view_mode == "week":
            week_start = today - timedelta(days=today.weekday())
            current_date = week_start + timedelta(weeks=page_offset)
            start_date = current_date
            end_date = start_date + timedelta(days=6)
            context["calendar_days"] = [start_date + timedelta(days=i) for i in range(7)]
            context["calendar_hours"] = list(range(0, 24))
        elif view_mode == "month":
            first_of_month = today.replace(day=1)
            month_offset = page_offset
            year = first_of_month.year + (first_of_month.month - 1 + month_offset) // 12
            month = (first_of_month.month - 1 + month_offset) % 12 + 1
            current_date = date(year, month, 1)
            start_date = current_date
            if month == 12:
                end_date = date(year + 1, 1, 1) - timedelta(days=1)
            else:
                end_date = date(year, month + 1, 1) - timedelta(days=1)
            context["calendar_weeks"] = self.build_month_calendar_grid(start_date, end_date)
        else:
            current_date = today
            start_date = today
            end_date = today

        context["calendar_current_date"] = current_date
        context["calendar_page_offset"] = page_offset
        context["calendar_date_range"] = {
            "start": start_date,
            "end": end_date,
        }

        filter_kwargs = {
            f"{field_name}__gte": start_date,
            f"{field_name}__lte": end_date + timedelta(days=1),
        }

        try:
            filtered_queryset = queryset.filter(**filter_kwargs)
        except Exception:
            filtered_queryset = queryset

        events_by_date = defaultdict(list)
        for obj in filtered_queryset:
            event_date_value = getattr(obj, field_name, None)
            if event_date_value:
                if isinstance(event_date_value, datetime):
                    event_date = event_date_value.date()
                    event_time = event_date_value.time()
                else:
                    event_date = event_date_value
                    event_time = None

                events_by_date[event_date].append({
                    "object": obj,
                    "date": event_date,
                    "time": event_time,
                    "datetime": event_date_value,
                })

        context["calendar_events_by_date"] = dict(events_by_date)
        context["calendar_events"] = list(filtered_queryset)
        return context

    @classmethod
    def get_start_field(cls, data_view_fields, options):
        return cls.get_field_from_data_view_fields(
            data_view_fields,
            getattr(options, "start_field_id", None),
        )

    @classmethod
    def get_end_field(cls, data_view_fields, options):
        return cls.get_field_from_data_view_fields(
            data_view_fields,
            getattr(options, "end_field_id", None),
        )

    @staticmethod
    def build_month_calendar_grid(start_date: date, end_date: date) -> list:
        weeks = []

        first_day_weekday = start_date.weekday()
        grid_start = start_date - timedelta(days=first_day_weekday)

        last_day_weekday = end_date.weekday()
        grid_end = end_date + timedelta(days=(6 - last_day_weekday))

        current_day = grid_start
        while current_day <= grid_end:
            week = []
            for _ in range(7):
                week.append({
                    "date": current_day,
                    "is_current_month": start_date <= current_day <= end_date,
                    "is_today": current_day == date.today(),
                })
                current_day += timedelta(days=1)
            weeks.append(week)

        return weeks
