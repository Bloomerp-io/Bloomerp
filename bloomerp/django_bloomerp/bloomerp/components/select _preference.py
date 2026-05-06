from __future__ import annotations

import copy
from enum import StrEnum

from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from bloomerp.models.users.base_view_preference import BaseViewPreference
from bloomerp.models.users.user_create_view_preference import UserCreateViewPreference
from bloomerp.models.users.user_detail_view_preference import UserDetailViewPreference
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.router import router
from bloomerp.utils.requests import render_page_refresh


class PreferenceType(StrEnum):
    CREATE = "create"
    DETAIL = "detail"
    LIST = "list"


PREFERENCE_MODEL_BY_TYPE: dict[PreferenceType, type[BaseViewPreference]] = {
    PreferenceType.CREATE: UserCreateViewPreference,
    PreferenceType.DETAIL: UserDetailViewPreference,
    PreferenceType.LIST: UserListViewPreference,
}


def _get_preference_model(preference_type: str) -> type[BaseViewPreference] | None:
    try:
        resolved_type = PreferenceType(preference_type)
    except ValueError:
        return None

    return PREFERENCE_MODEL_BY_TYPE.get(resolved_type)


def _clone_preference_fields(preference: BaseViewPreference) -> dict:
    cloned_fields: dict[str, object] = {}
    excluded_fields = {"id", "pk", "user_id", "content_type_id", "selected", "name"}

    for field in preference._meta.concrete_fields:
        if field.attname in excluded_fields:
            continue
        cloned_fields[field.attname] = copy.deepcopy(getattr(preference, field.attname))

    return cloned_fields

@router.register(
    path="components/select_preference/<int:content_type_id>/<str:type>/",
    name="components_select_preference",
)
def select_preference(request: HttpRequest, content_type_id: int, type: str) -> HttpResponse:
    preference_model = _get_preference_model(type)
    if preference_model is None:
        return HttpResponse("Invalid preference type", status=400)

    content_type = get_object_or_404(ContentType, id=content_type_id)

    if request.method == "POST":
        if request.POST.get("action") == "select":
            preference = get_object_or_404(
                preference_model,
                pk=request.POST.get("preference_id"),
                user=request.user,
                content_type=content_type,
            )
            preference.select()
            return render_page_refresh()

        if request.POST.get("action") == "create":
            name = (request.POST.get("name") or "").strip()
            current_preference = preference_model.get_or_create_for_user(request.user, content_type)

            if not name:
                preferences = preference_model.objects.filter(
                    user=request.user,
                    content_type=content_type,
                ).order_by("-selected", "name", "pk")
                return render(
                    request,
                    "components/select_preference.html",
                    {
                        "preferences": preferences,
                        "current_preference": current_preference,
                        "content_type_id": content_type_id,
                        "type": type,
                        "error": "Preference name is required.",
                    },
                    status=400,
                )

            preference_model.objects.create(
                user=request.user,
                content_type=content_type,
                name=name,
                selected=True,
                **_clone_preference_fields(current_preference),
            )
            return render_page_refresh()

        return HttpResponse("Invalid action", status=400)

    if request.method != "GET":
        return HttpResponse("Method not allowed", status=405)

    current_preference = preference_model.get_or_create_for_user(request.user, content_type)
    preferences = preference_model.objects.filter(
        user=request.user,
        content_type=content_type,
    ).order_by("-selected", "name", "pk")

    return render(
        request,
        "components/select_preference.html",
        {
            "preferences": preferences,
            "current_preference": current_preference,
            "content_type_id": content_type_id,
            "type": type,
        },
    )
