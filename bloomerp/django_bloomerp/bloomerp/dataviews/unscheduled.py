"""Shared sidebar and date clearing for schedulable dataviews."""

from collections.abc import Callable
from typing import Any

from django.core.exceptions import ValidationError
from django.core.paginator import Page
from django.db import IntegrityError, transaction
from django.db.models import Model, QuerySet
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse

from bloomerp.models.application_field import ApplicationField

from .definition import DataviewState


class UnscheduledDataviewMixin:
    """Support unscheduled records for renderers that display scheduling dates."""

    state: DataviewState
    item_template_name: str
    paginate_object_list: Callable[[Any, int, Any], Page]

    def paginate_unscheduled(self, queryset: QuerySet[Model], page_size: int, page_param: str) -> Page:
        """Paginate unscheduled records, matching the same labels the sidebar displays."""
        request = self.state.request
        search = request.GET.get("unscheduled_q", "").strip().casefold()
        if not queryset.query.order_by:
            queryset = queryset.order_by("pk")
        objects = (
            [obj for obj in queryset.iterator(chunk_size=2000) if search in str(obj).casefold()]
            if search else queryset
        )
        return self.paginate_object_list(objects, page_size, request.GET.get(page_param, 1))

    def unscheduled_context(
        self, page: Page, items: list[dict[str, Any]], page_param: str,
    ) -> dict[str, Any]:
        """Build the shared sidebar URLs while preserving the originating view's filters."""
        kwargs: dict[str, int | str] = {"content_type_id": self.state.content_type_id, "action": "unscheduled"}
        if self.state.preference.pk is not None:
            kwargs["preference_id"] = self.state.preference.pk
        url = reverse("components_dataview_renderer_operation", kwargs=kwargs)
        query = self.state.request.GET.copy()
        for key in ("page", "gant_page", page_param):
            query.pop(key, None)
        search = query.get("unscheduled_q", "").strip()
        query.pop("unscheduled_q", None)
        search_url = f"{url}?{query.urlencode()}" if query else url
        if search:
            query["unscheduled_q"] = search
        next_url = ""
        if page.has_next():
            query[page_param] = page.next_page_number()
            next_url = f"{url}?{query.urlencode()}"
        return {
            "unscheduled_search_url": search_url,
            "unscheduled_search": search,
            "unscheduled_items": items,
            "unscheduled_next_url": next_url,
        }

    def render_unscheduled(self, context: dict[str, Any]) -> HttpResponse:
        """Render only the unscheduled results for a search or pagination request."""
        from bloomerp.components.objects.dataviews.dataview import (
            build_dataview_action_context,
        )

        return render(self.state.request, "dataview/unscheduled_results.html", {
            "content_type_id": self.state.content_type_id,
            "dataview_item_template": self.item_template_name,
            "object_actions": self.state.object_actions,
            **context,
            "dataview_action_context": build_dataview_action_context(self.state.request, self.state),
        })

    @staticmethod
    def scheduling_dates_are_optional(*fields: ApplicationField) -> bool:
        """Check whether the configured date fields accept an empty value."""
        return bool(fields) and all(
            model_field.null and model_field.blank
            for model_field in (field._get_model_field() for field in fields)
        )

    def get_unschedule_fields(self, _obj: Model) -> tuple[ApplicationField, ...]:
        """Return the date fields a renderer uses to schedule this record."""
        return ()

    def unschedule_record(self) -> HttpResponse:
        """Clear one visible record's scheduling dates after checking write permissions."""
        from bloomerp.permissions.definition import BloomerpPermission
        from bloomerp.permissions.manager import UserPolicyManager

        request = self.state.request
        try:
            pk = self.state.model._meta.pk.to_python(request.POST.get("object_id"))
        except (TypeError, ValueError, ValidationError):
            return HttpResponse("Invalid record ID", status=400)
        if pk is None:
            return HttpResponse("A record ID is required", status=400)

        manager = UserPolicyManager(request.user)
        if not manager.has_global_permission(self.state.model, BloomerpPermission.CHANGE):
            return HttpResponse("Permission denied", status=403)

        try:
            with transaction.atomic():
                obj = (
                    manager.get_queryset(self.state.model, BloomerpPermission.CHANGE)
                    .select_for_update()
                    .filter(pk=pk, pk__in=self.state.queryset.order_by().values("pk"))
                    .first()
                )
                if obj is None:
                    return HttpResponse("Permission denied", status=403)
                fields = self.get_unschedule_fields(obj)
                if not self.scheduling_dates_are_optional(*fields):
                    return HttpResponse("This record requires its scheduling dates", status=409)
                field_names = list(dict.fromkeys(field.field for field in fields))
                if any(not field._get_model_field().editable for field in fields) or any(
                    not manager.has_access_to_object(obj, permission, fields=field_names)
                    for permission in (BloomerpPermission.VIEW, BloomerpPermission.CHANGE)
                ):
                    return HttpResponse("Permission denied", status=403)
                if all(getattr(obj, field_name) is None for field_name in field_names):
                    return HttpResponse(status=204)
                for field_name in field_names:
                    setattr(obj, field_name, None)
                obj.clean()
                if any(getattr(obj, field_name) is not None for field_name in field_names):
                    raise ValidationError("The model requires scheduling dates.")
                obj.save(update_fields=field_names)
        except (IntegrityError, ValidationError):
            return HttpResponse("This record cannot be unscheduled", status=409)
        return HttpResponse(status=204)
