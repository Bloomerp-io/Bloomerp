from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from math import isfinite
from typing import Any, Iterable

from django.db import transaction
from django.db.models import Max, Min, Q, QuerySet
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone

from bloomerp.models.application_field import ApplicationField
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager

from ..definition import BaseDataviewRenderer, DataviewPagination, DataviewRenderState


class GanttDataviewRenderer(BaseDataviewRenderer):
    """Render records as rows on a horizontally scaled Gantt timeline."""

    template_name = "cotton/features/dataviews/gant.html"
    reserved_query_params = {"gant_page", "gant_unscheduled_page"}

    @classmethod
    def paginate_queryset(
        cls,
        queryset: QuerySet,
        preference,
        request: HttpRequest,
        options: object | None = None,
    ) -> DataviewPagination:
        """Paginate Gantt rows for intersection-triggered incremental loading."""
        start_field = cls._configured_field(
            preference,
            request,
            getattr(options, "start_field_id", None),
        )
        end_field = cls._configured_field(
            preference,
            request,
            getattr(options, "end_field_id", None),
        )
        if start_field is not None and end_field is not None:
            queryset = queryset.filter(
                **{
                    f"{start_field.field}__isnull": False,
                    f"{end_field.field}__isnull": False,
                },
            ).order_by(start_field.field, "pk")

        page_size = int(getattr(options, "page_size", 25))
        page_obj = cls.paginate_object_list(
            queryset,
            page_size,
            request.GET.get("gant_page", 1),
        )
        return DataviewPagination(queryset=page_obj, page_obj=page_obj)

    def get_context_data(self, pagination: DataviewPagination) -> dict[str, Any]:
        context = super().get_context_data(pagination)
        context.update(self._build_gant_context(pagination.queryset))
        return context

    def _build_gant_context(self, objects: Iterable) -> dict[str, Any]:
        start_field = self.get_field_from_data_view_fields(
            self.state.fields,
            getattr(self.options, "start_field_id", None),
        )
        end_field = self.get_field_from_data_view_fields(
            self.state.fields,
            getattr(self.options, "end_field_id", None),
        )
        dependency_from_field = self._get_self_relation_field(
            getattr(self.options, "dependency_from_field_id", None),
        )
        dependency_for_field = self._get_self_relation_field(
            getattr(self.options, "dependency_for_field_id", None),
        )

        context: dict[str, Any] = {
            "gant_configured": bool(start_field and end_field),
            "gant_rows": [],
            "gant_start": None,
            "gant_end": None,
            "gant_start_ms": None,
            "gant_end_ms": None,
            "gant_page_querystring": self.build_querystring(
                self.state.request,
                ("page", "gant_page", "gant_unscheduled_page"),
            ),
            "gant_unscheduled_rows": [],
            "gant_unscheduled_page_obj": None,
            "gant_unscheduled_querystring": self.build_querystring(
                self.state.request,
                ("page", "gant_page", "gant_unscheduled_page"),
            ),
        }
        if not start_field or not end_field:
            return context

        timeline_start, timeline_end = self._get_timeline_range(
            self.state.queryset,
            start_field,
            end_field,
        )

        unscheduled_page = self._get_unscheduled_page(start_field, end_field)
        context.update({
            "gant_start": timeline_start,
            "gant_end": timeline_end,
            "gant_start_ms": self._to_milliseconds(timeline_start),
            "gant_end_ms": self._to_milliseconds(timeline_end),
            "gant_start_field_type": start_field.field_type,
            "gant_end_field_type": end_field.field_type,
            "gant_rows": [
                self._build_row(
                    obj,
                    start_field,
                    end_field,
                    dependency_from_field,
                    dependency_for_field,
                )
                for obj in objects
            ],
            "gant_unscheduled_rows": [
                self._build_row(
                    obj,
                    start_field,
                    end_field,
                    dependency_from_field,
                    dependency_for_field,
                )
                for obj in unscheduled_page
            ],
            "gant_unscheduled_page_obj": unscheduled_page,
        })
        return context

    def _get_unscheduled_page(
        self,
        start_field: ApplicationField,
        end_field: ApplicationField,
    ):
        queryset = self.state.queryset.filter(
            Q(**{f"{start_field.field}__isnull": True})
            | Q(**{f"{end_field.field}__isnull": True}),
        ).order_by("pk")
        return self.paginate_object_list(
            queryset,
            int(getattr(self.options, "page_size", 25)),
            self.state.request.GET.get("gant_unscheduled_page", 1),
        )

    @classmethod
    def handle_action(cls, action: str, request, state) -> HttpResponse:
        if action == "dates":
            return cls._update_dates(request, state)

        if action not in {"page", "unscheduled"}:
            return super().handle_action(action, request, state)

        if request.method != "GET":
            return HttpResponse("Method not allowed", status=405)

        pagination = cls.paginate_queryset(
            state.queryset,
            state.preference,
            request,
            state.dataview_options,
        )
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
        context = renderer.get_context_data(pagination)
        context["page_obj"] = pagination.page_obj
        if action == "unscheduled":
            return render(request, "components/objects/dataview_gant_unscheduled.html", context)
        return render(request, "components/objects/dataview_gant_rows.html", context)

    @classmethod
    def _update_dates(cls, request: HttpRequest, state) -> HttpResponse:
        if request.method != "POST":
            return HttpResponse("Method not allowed", status=405)

        try:
            payload = json.loads(request.body)
        except (TypeError, ValueError, json.JSONDecodeError):
            return HttpResponse("Invalid JSON payload", status=400)

        updates = payload.get("updates") if isinstance(payload, dict) else None
        if not isinstance(updates, list) or not 1 <= len(updates) <= 100:
            return HttpResponse("Expected between 1 and 100 updates", status=400)

        start_field = cls._configured_field_for_content_type(
            state.content_type,
            getattr(state.dataview_options, "start_field_id", None),
        )
        end_field = cls._configured_field_for_content_type(
            state.content_type,
            getattr(state.dataview_options, "end_field_id", None),
        )
        if start_field is None or end_field is None:
            return HttpResponse("Gantt date fields are not configured", status=400)

        permission_manager = UserPolicyManager(request.user)
        if not permission_manager.has_global_permission(state.model, BloomerpPermission.CHANGE):
            return HttpResponse("Permission denied", status=403)

        requested_field_keys = {
            key
            for update in updates
            if isinstance(update, dict)
            for key in ("start_ms", "end_ms")
            if key in update
        }
        if not requested_field_keys:
            return HttpResponse("No date values supplied", status=400)
        fields_by_key = {"start_ms": start_field, "end_ms": end_field}
        if any(
            not cls._field_is_editable(fields_by_key[key])
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
                    if "start_ms" in update:
                        setattr(
                            obj,
                            start_field.field,
                            cls._stored_date_value(update["start_ms"], start_field, is_end=False),
                        )
                        changed_fields.append(start_field.field)
                    if "end_ms" in update:
                        setattr(
                            obj,
                            end_field.field,
                            cls._stored_date_value(update["end_ms"], end_field, is_end=True),
                        )
                        changed_fields.append(end_field.field)
                except (OverflowError, TypeError, ValueError):
                    return HttpResponse("Invalid date value", status=400)

                display_start = cls._as_datetime(getattr(obj, start_field.field, None))
                display_end = cls._as_datetime(
                    getattr(obj, end_field.field, None),
                    end_of_date=end_field.field_type == "DateField",
                )
                if display_start is not None and display_end is not None and display_end <= display_start:
                    return HttpResponse("End must be after start", status=400)

                pending_saves.append((obj, list(dict.fromkeys(changed_fields))))

            response_updates = []
            for obj, changed_fields in pending_saves:
                obj.save(update_fields=changed_fields)
                display_start = cls._as_datetime(getattr(obj, start_field.field, None))
                display_end = cls._as_datetime(
                    getattr(obj, end_field.field, None),
                    end_of_date=end_field.field_type == "DateField",
                )
                response_updates.append({
                    "object_id": str(obj.pk),
                    "start_ms": cls._to_milliseconds(display_start),
                    "end_ms": cls._to_milliseconds(display_end),
                })

        return JsonResponse({"status": "ok", "updates": response_updates})

    @staticmethod
    def _configured_field_for_content_type(content_type, field_id):
        if field_id in (None, ""):
            return None
        try:
            application_field = ApplicationField.objects.get(
                pk=int(field_id),
                content_type=content_type,
            )
        except (TypeError, ValueError, ApplicationField.DoesNotExist):
            return None
        if application_field.field_type not in {"DateField", "DateTimeField"}:
            return None
        return application_field

    @staticmethod
    def _field_is_editable(application_field: ApplicationField) -> bool:
        model = application_field.content_type.model_class()
        if model is None:
            return False
        return bool(model._meta.get_field(application_field.field).editable)

    @classmethod
    def _stored_date_value(
        cls,
        timestamp_ms,
        application_field: ApplicationField,
        *,
        is_end: bool,
    ):
        numeric_timestamp = float(timestamp_ms)
        if not isfinite(numeric_timestamp):
            raise ValueError("Timestamp must be finite")
        value = datetime.fromtimestamp(
            numeric_timestamp / 1000,
            tz=timezone.get_current_timezone(),
        )
        if application_field.field_type == "DateTimeField":
            return value
        if is_end:
            value -= timedelta(milliseconds=1)
        return value.date()

    def _get_self_relation_field(self, field_id):
        application_field = self.get_field_from_data_view_fields(self.state.fields, field_id)
        if application_field is None:
            return None
        if application_field.field_type not in {"ForeignKey", "OneToOneField"}:
            return None
        if application_field.related_model_id != application_field.content_type_id:
            return None
        return application_field

    @staticmethod
    def _configured_field(preference, request: HttpRequest, field_id):
        if field_id in (None, ""):
            return None
        try:
            application_field = preference.content_type.applicationfield_set.get(pk=int(field_id))
        except (TypeError, ValueError, ApplicationField.DoesNotExist):
            return None

        if application_field.field_type not in {"DateField", "DateTimeField"}:
            return None
        if not UserPolicyManager(request.user).has_field_permission(application_field, BloomerpPermission.VIEW):
            return None
        return application_field

    @classmethod
    def _get_timeline_range(
        cls,
        queryset: QuerySet,
        start_field: ApplicationField,
        end_field: ApplicationField,
    ) -> tuple[datetime, datetime]:
        scheduled_queryset = queryset.filter(
            **{
                f"{start_field.field}__isnull": False,
                f"{end_field.field}__isnull": False,
            },
        )
        bounds = scheduled_queryset.aggregate(
            gant_start=Min(start_field.field),
            gant_end=Max(end_field.field),
        )
        timeline_start = cls._as_datetime(bounds["gant_start"])
        timeline_end = cls._as_datetime(
            bounds["gant_end"],
            end_of_date=end_field.field_type == "DateField",
        )
        now = timezone.localtime()

        if timeline_start is None and timeline_end is None:
            return now, now + timedelta(hours=1)
        if timeline_start is None:
            timeline_start = timeline_end
        if timeline_end is None:
            timeline_end = timeline_start
        if timeline_end < timeline_start:
            timeline_end = timeline_start
        return timeline_start, timeline_end

    def _build_row(
        self,
        obj,
        start_field: ApplicationField,
        end_field: ApplicationField,
        dependency_from_field,
        dependency_for_field,
    ) -> dict[str, Any]:
        start_value = getattr(obj, start_field.field, None)
        end_value = getattr(obj, end_field.field, None)
        item_start = self._as_datetime(start_value)
        item_end = self._as_datetime(
            end_value,
            end_of_date=end_field.field_type == "DateField",
        )
        scheduled = item_start is not None and item_end is not None

        if scheduled:
            if item_end < item_start:
                item_end = item_start

        can_edit_start, can_edit_end = self._edit_permissions_for_object(
            obj,
            start_field,
            end_field,
        )

        return {
            "object": obj,
            "start": start_value,
            "end": end_value,
            "scheduled": scheduled,
            "start_ms": self._to_milliseconds(item_start),
            "end_ms": self._to_milliseconds(item_end),
            "shows_time": (
                start_field.field_type == "DateTimeField"
                or end_field.field_type == "DateTimeField"
            ),
            "can_edit_start": can_edit_start,
            "can_edit_end": can_edit_end,
            "dependency_from_id": self._related_object_id(obj, dependency_from_field),
            "dependency_for_id": self._related_object_id(obj, dependency_for_field),
        }

    def _edit_permissions_for_object(
        self,
        obj,
        start_field: ApplicationField,
        end_field: ApplicationField,
    ) -> tuple[bool, bool]:
        permission = BloomerpPermission.CHANGE
        permission_manager = UserPolicyManager(self.state.request.user)
        can_edit_row = permission_manager.has_access_to_object(obj, permission)
        if not can_edit_row:
            return False, False
        return (
            self._field_is_editable(start_field)
            and permission_manager.has_field_permission(start_field, permission),
            self._field_is_editable(end_field)
            and permission_manager.has_field_permission(end_field, permission),
        )

    @staticmethod
    def _related_object_id(obj, application_field) -> str:
        if application_field is None:
            return ""
        try:
            model_field = obj._meta.get_field(application_field.field)
        except Exception:
            return ""
        value = getattr(obj, model_field.attname, None)
        return "" if value is None else str(value)

    @staticmethod
    def _as_datetime(value, *, end_of_date: bool = False) -> datetime | None:
        """Normalize date values without discarding DateTimeField precision."""
        if isinstance(value, datetime):
            result = value
        elif isinstance(value, date):
            result = datetime.combine(value, time.min)
            if end_of_date:
                result += timedelta(days=1)
        else:
            return None

        if timezone.is_naive(result):
            result = timezone.make_aware(result, timezone.get_current_timezone())
        return result

    @staticmethod
    def _to_milliseconds(value: datetime | None) -> int | None:
        """Return a browser-friendly Unix timestamp in milliseconds."""
        if value is None:
            return None
        return round(value.timestamp() * 1000)
