import json

from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from bloomerp.models import ApplicationField
from bloomerp.models.forms.form import Form
from bloomerp.models.users.user_object_layout_preference import (
    UserObjectLayoutPreference,
)
from bloomerp.models.workspaces.tile import Tile
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.permissions.manager import UserPolicyManager, create_permission_str
from bloomerp.router import router
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.services.sectioned_layout_services import (
    get_available_layout_fields,
    normalize_layout_payload,
)


def _get_payload_target_content_type_id(payload: dict) -> str | int | None:
    value = payload.get("target_content_type_id") or payload.get("content_type_id")
    return value if isinstance(value, (str, int)) else None


def _get_valid_field_ids(
    request: HttpRequest,
    *,
    content_type: ContentType,
    scope: str,
) -> set[str]:
    return {
        str(item["id"])
        for item in get_available_layout_fields(
            content_type=content_type,
            user=request.user,
            layout_kind=scope,
        )
    }


def _get_protected_field_ids(
    request: HttpRequest,
    *,
    content_type: ContentType,
    scope: str,
    existing_ids: set[str],
) -> set[str]:
    """Protect denied fields, not fields omitted from the presentation catalog.

    Header-managed fields may remain in older saved layouts even though they
    cannot be added through the layout picker. Their row metadata and removal
    still follow ordinary field permissions.
    """
    model = content_type.model_class()
    permission = create_permission_str(model, "add" if scope == "create" else "view")
    manager = UserPolicyManager(request.user)
    permitted_ids = {
        str(field.pk)
        for field in ApplicationField.objects.filter(
            content_type=content_type, pk__in=existing_ids
        )
        if manager.has_field_permission(field, permission)
    }
    return existing_ids - permitted_ids


def _protected_layout_items_are_unchanged(
    *,
    existing_layout,
    submitted_layout,
    protected_ids: set[str],
) -> bool:
    def item_states(layout):
        states = {}
        for row_index, row in enumerate(layout.rows):
            for item in row.items:
                states[str(item.id)] = (
                    row_index,
                    row.columns,
                    row.title,
                    item.colspan,
                    item.config,
                )
        return states

    existing_states = item_states(existing_layout)
    submitted_states = item_states(submitted_layout)
    return all(
        submitted_states.get(field_id) == existing_states.get(field_id)
        for field_id in protected_ids
    )


def _save_layout_preference(
    request: HttpRequest,
    *,
    payload: dict,
    content_type: ContentType,
    model: type[Model],
    scope: str,
    preference: UserObjectLayoutPreference,
) -> HttpResponse:
    """Save an authorized layout while preserving genuinely inaccessible fields."""
    manager = UserPolicyManager(request.user)
    target_content_type_id = _get_payload_target_content_type_id(payload)
    if target_content_type_id and str(target_content_type_id) != str(content_type.id):
        return HttpResponse("target_content_type_id does not match route", status=400)

    permission = create_permission_str(model, "add" if scope == "create" else "view")
    if not manager.has_global_permission(model, permission):
        return HttpResponse("Permission denied", status=403)

    layout = normalize_layout_payload(payload.get("layout"))
    submitted_ids = {str(item.id) for row in layout.rows for item in row.items}
    known_ids = {
        str(field_id)
        for field_id in ApplicationField.get_for_model(model).values_list("id", flat=True)
    }
    if not submitted_ids.issubset(known_ids):
        invalid_ids = sorted(submitted_ids - known_ids)
        return JsonResponse(
            {"error": "Unknown field id in layout", "invalid_ids": invalid_ids},
            status=400,
        )

    existing_ids = {
        str(item.id)
        for row in preference.layout_obj.rows
        for item in row.items
    }
    newly_added_ids = submitted_ids - existing_ids
    valid_new_ids = _get_valid_field_ids(
        request,
        content_type=content_type,
        scope=scope,
    )
    if not newly_added_ids.issubset(valid_new_ids):
        invalid_ids = sorted(newly_added_ids - valid_new_ids)
        return JsonResponse(
            {"error": "Permission denied for layout field", "invalid_ids": invalid_ids},
            status=403,
        )

    protected_ids = _get_protected_field_ids(
        request, content_type=content_type, scope=scope, existing_ids=existing_ids
    )
    if not _protected_layout_items_are_unchanged(
        existing_layout=preference.layout_obj,
        submitted_layout=layout,
        protected_ids=protected_ids,
    ):
        return JsonResponse(
            {
                "error": "Permission denied for protected layout field",
                "invalid_ids": sorted(protected_ids),
            },
            status=403,
        )

    preference.layout = layout.model_dump()
    preference.save(update_fields=["layout"])
    return JsonResponse({"status": "ok", "layout": layout.model_dump()})

# ---------------------------------------------------------------------------
# Callables
# ---------------------------------------------------------------------------
def _save_workspace(
    request: HttpRequest,
    workspace: Workspace,
    payload: dict,
) -> JsonResponse:
    if workspace.user_id != request.user.id:
        return JsonResponse(
            {"status": "error", "message": "Permission denied"},
            status=403,
        )

    layout = normalize_layout_payload(payload.get("layout"))
    valid_ids = {str(tile_id) for tile_id in Tile.objects.values_list("id", flat=True)}
    requested_ids = {str(item.id) for row in layout.rows for item in row.items}
    if not requested_ids.issubset(valid_ids):
        return JsonResponse(
            {"status": "error", "message": "Unknown tile id in layout"},
            status=400,
        )

    workspace.layout = layout.model_dump()
    workspace.save(update_fields=["layout"])
    return JsonResponse({"status": "ok", "layout": layout.model_dump()})


def _save_form(request: HttpRequest, form: Form, payload: dict) -> HttpResponse:
    """Save an authorized layout while preserving genuinely inaccessible fields."""
    manager = UserPolicyManager(request.user)
    if not manager.has_access_to_object(form, create_permission_str(form, "change")):
        return HttpResponse("Permission denied", status=403)

    target_content_type = form.content_type
    target_content_type_id = _get_payload_target_content_type_id(payload)
    if target_content_type_id and str(target_content_type_id) != str(
        target_content_type.id
    ):
        return HttpResponse(
            "target_content_type_id does not match form target",
            status=400,
        )

    layout = normalize_layout_payload(payload.get("layout"))
    valid_ids = _get_valid_field_ids(request, content_type=target_content_type, scope="create")
    submitted_ids = {str(item.id) for row in layout.rows for item in row.items}
    known_ids = {
        str(field_id)
        for field_id in ApplicationField.objects.filter(
            content_type=target_content_type,
        ).values_list("id", flat=True)
    }
    if not submitted_ids.issubset(known_ids):
        invalid_ids = sorted(submitted_ids - known_ids)
        return JsonResponse(
            {"error": "Unknown field id in layout", "invalid_ids": invalid_ids},
            status=400,
        )

    existing_ids = {
        str(item.id)
        for row in form.layout_obj.rows
        for item in row.items
    }
    newly_added_ids = submitted_ids - existing_ids
    if not newly_added_ids.issubset(valid_ids):
        invalid_ids = sorted(newly_added_ids - valid_ids)
        return JsonResponse(
            {"error": "Permission denied for layout field", "invalid_ids": invalid_ids},
            status=403,
        )

    protected_ids = _get_protected_field_ids(
        request, content_type=target_content_type, scope="create", existing_ids=existing_ids
    )
    if not _protected_layout_items_are_unchanged(
        existing_layout=form.layout_obj,
        submitted_layout=layout,
        protected_ids=protected_ids,
    ):
        return JsonResponse(
            {
                "error": "Permission denied for protected layout field",
                "invalid_ids": sorted(protected_ids),
            },
            status=403,
        )

    form.layout = layout.model_dump()
    form.save(update_fields=["layout"])
    return JsonResponse({"status": "ok", "layout": layout.model_dump()})


def _save_user_object_layout_preference(
    request: HttpRequest,
    preference: UserObjectLayoutPreference,
    payload: dict,
) -> HttpResponse:
    scope = request.GET.get("layout_mode", "detail")
    if scope not in {"create", "detail"}:
        return HttpResponse("Invalid layout mode", status=400)
    if not PreferenceManager(request.user).can_manage(preference):
        return HttpResponse("Permission denied", status=403)

    content_type = preference.content_type
    model = content_type.model_class()
    if model is None:
        return HttpResponse("Invalid content type", status=400)
    return _save_layout_preference(
        request,
        payload=payload,
        content_type=content_type,
        model=model,
        scope=scope,
        preference=preference,
    )


CALLABLES = {
    Workspace: _save_workspace,
    Form: _save_form,
    UserObjectLayoutPreference: _save_user_object_layout_preference,
}


@router.register(
    path="components/layout/save-layout-object/<int:content_type_id>/<str:object_id>/",
    name="components_save_layout_object"
)
@require_POST
def save_layout_object(
    request: HttpRequest,
    content_type_id: int,
    object_id: str,
) -> HttpResponse:
    """Endpoint to save a layout object"""
    content_type: ContentType = get_object_or_404(ContentType, id=content_type_id)
    model_cls = content_type.model_class()
    if model_cls is None:
        return HttpResponse("Invalid content type", status=400)

    func = CALLABLES.get(model_cls)
    if not func:
        raise Http404()

    obj = get_object_or_404(model_cls, id=object_id)

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON body", status=400)

    result = func(request, obj, payload)
    if isinstance(result, HttpResponse):
        return result
    return JsonResponse(result)
