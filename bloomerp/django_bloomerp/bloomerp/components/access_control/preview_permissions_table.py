import json
from collections import OrderedDict

from django.contrib.contenttypes.models import ContentType
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from bloomerp.field_types import FieldType
from bloomerp.models import ApplicationField
from bloomerp.router import router
from bloomerp.services.permission_services import UserPermissionManager

PREVIEW_PAGE_SIZE = 10


def _parse_json_payload(raw_value: str | None, fallback):
    if not raw_value:
        return fallback

    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        return fallback


def _build_preview_queryset(
    request: HttpRequest,
    content_type: ContentType,
    row_policy_rules: list[dict],
):
    model = content_type.model_class()
    if model is None:
        return None

    permission_manager = UserPermissionManager(request.user)
    rule_dicts = [
        rule_dict
        for row_policy_rule in row_policy_rules
        for rule_dict in [row_policy_rule.get("rule") or {}]
        if isinstance(rule_dict, dict)
    ]
    return permission_manager.build_queryset_from_rule_dicts(content_type, rule_dicts)


def _format_permission_label(permission_codename: str) -> str:
    action = str(permission_codename or "").split("_", 1)[0].replace("_", " ").strip()
    return action.replace("bulk ", "bulk ").title() if action else "Unknown"


def _format_permission_tooltip(permission_codenames: list[str]) -> str:
    if not permission_codenames:
        return "No actions configured."

    labels = [_format_permission_label(permission_codename) for permission_codename in permission_codenames]
    return "Field actions: " + ", ".join(labels)


def _get_preview_columns(content_type: ContentType, field_policies: dict) -> list[dict]:
    if not isinstance(field_policies, dict):
        return []

    selected_field_ids = [str(field_id) for field_id in field_policies.keys() if str(field_id) != "__all__"]
    if not selected_field_ids:
        return []

    application_fields = ApplicationField.objects.filter(
        content_type=content_type,
        id__in=selected_field_ids,
    )
    field_lookup = {str(application_field.id): application_field for application_field in application_fields}

    columns = []
    for field_id in selected_field_ids:
        application_field = field_lookup.get(field_id)
        if not application_field:
            continue

        permission_codenames = [str(permission) for permission in field_policies.get(field_id, [])]
        columns.append(
            {
                "field": application_field,
                "title": application_field.title,
                "is_field_type": FieldType.template_context(application_field.field_type),
                "tooltip_text": _format_permission_tooltip(permission_codenames),
            }
        )

    return columns


def _build_preview_rows(
    page_obj,
    row_policy_rules: list[dict],
    permission_manager: UserPermissionManager,
    preview_columns: list[dict],
) -> list[dict]:
    preview_rows = []

    for obj in page_obj.object_list:
        matched_permissions = OrderedDict()

        for row_policy_rule in row_policy_rules:
            rule_dict = row_policy_rule.get("rule") or {}
            rule_q = permission_manager.build_q_for_rule_dict(rule_dict)
            if rule_q is None:
                continue

            if not obj.__class__.objects.filter(pk=obj.pk).filter(rule_q).exists():
                continue

            for permission_codename in row_policy_rule.get("permissions", []):
                matched_permissions[str(permission_codename)] = _format_permission_label(str(permission_codename))

        cells = []
        for column in preview_columns:
            application_field = column["field"]
            value = getattr(obj, application_field.field, None)
            cells.append(
                {
                    "field": application_field,
                    "value": value,
                    "value_content_type_id": application_field.related_model_id,
                    "is_field_type": column["is_field_type"],
                    "tooltip_text": column["tooltip_text"],
                }
            )

        preview_rows.append(
            {
                "object": obj,
                "row_permissions": list(matched_permissions.values()),
                "cells": cells,
            }
        )

    return preview_rows


@router.register(
    path="components/access-control/preview-permissions-table/<int:content_type_id>/",
    name="components_preview_permissions_table",
)
def preview_permissions_table(request: HttpRequest, content_type_id: int) -> HttpResponse:
    """
    Render a lightweight preview of the objects visible for the current draft policy.
    """
    content_type = get_object_or_404(ContentType, id=content_type_id)
    model = content_type.model_class()
    if model is None:
        return HttpResponse("Invalid content type.", status=400)

    payload = request.POST if request.method == "POST" else request.GET
    row_policy_rules = _parse_json_payload(payload.get("row_policy_rules_json"), [])
    field_policies = _parse_json_payload(payload.get("field_policies_json"), {})

    try:
        page_number = int(payload.get("page", "1"))
    except (TypeError, ValueError):
        page_number = 1

    queryset = _build_preview_queryset(request, content_type, row_policy_rules)
    if queryset is None:
        return HttpResponse("Unable to build preview.", status=400)
    permission_manager = UserPermissionManager(request.user)
    preview_columns = _get_preview_columns(content_type, field_policies)

    paginator = Paginator(queryset, PREVIEW_PAGE_SIZE)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages if paginator.num_pages else 1)
    preview_rows = _build_preview_rows(page_obj, row_policy_rules, permission_manager, preview_columns)

    return render(
        request,
        "components/access_control/preview_permissions_table.html",
        {
            "content_type_id": content_type_id,
            "model_name": model._meta.verbose_name.title(),
            "page_obj": page_obj,
            "page_number": page_obj.number if paginator.num_pages else 1,
            "total_pages": paginator.num_pages,
            "total_count": paginator.count,
            "has_row_rules": bool(row_policy_rules),
            "preview_columns": preview_columns,
            "preview_rows": preview_rows,
            "previous_page_number": page_obj.previous_page_number() if page_obj.has_previous() else None,
            "next_page_number": page_obj.next_page_number() if page_obj.has_next() else None,
        },
    )
