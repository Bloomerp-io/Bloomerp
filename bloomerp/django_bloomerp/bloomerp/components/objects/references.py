"""Search readable reference targets for editors and object attachment menus."""

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from bloomerp.files.access import FileAccessManager
from bloomerp.models import File, FileNode, FileReference, Label
from bloomerp.models.definition import get_model_config
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.router import router
from bloomerp.services.object_reference_services import (
    object_reference_metadata,
    reference_display,
    supports_object_references,
)
from bloomerp.services.search_services import SearchManager


@router.register(
    path="components/objects/references",
    url_name="components_objects_references",
)
@login_required
@require_GET
def reference_search(request: HttpRequest) -> JsonResponse:
    """Return bounded search results after filtering target rows and display fields."""
    kind = request.GET.get("kind", "user")
    query = request.GET.get("q", "").strip()[:100]
    items: list[dict[str, str | int]] = []
    if kind == "label":
        items = [
            {"kind": kind, "target_id": str(label.pk), "label": label.name}
            for label in Label.objects.filter(name__icontains=query).order_by("name")[
                :20
            ]
        ]
    elif kind == "file":
        files = FileNode.objects.filter(kind="FILE", name__icontains=query)
        if request.GET.get("images") == "true":
            files = files.filter(
                meta__mime_type__in=[
                    "image/png",
                    "image/jpeg",
                    "image/gif",
                    "image/webp",
                    "image/avif",
                ]
            )
        files = files.order_by("name")[:100]
        for file in files:
            if FileAccessManager(request.user).can_read_file_node(file):
                items.append(
                    {
                        "kind": kind,
                        "target_id": str(file.pk),
                        "label": file.name or "File",
                        "icon" : f"fa fa-file-{file.metadata.extension}"
                    }
                )
    elif kind in {"user", "object"}:
        search = SearchManager(request.user)
        candidates = (
            [get_user_model()]
            if kind == "user"
            else [
                model
                for model in search.permission_manager.get_accessible_models(
                    BloomerpPermission.VIEW
                )
                if supports_object_references(model)
            ]
        )
        result = search.search_objects(
            query,
            models=candidates,
            exclude_models=[File, FileNode, FileReference, get_user_model(), Label]
            if kind == "object"
            else None,
            per_model_limit=100,
            total_limit=100,
            allow_empty=True,
        )
        for obj in result.items:
            model = type(obj)
            if kind == "user" and not (obj.is_staff and obj.is_active):
                continue
            label = reference_display(request, obj)
            if label:
                config = get_model_config(model)
                items.append(
                    {
                        "kind": kind,
                        "target_id": str(obj.pk),
                        "content_type_id": ContentType.objects.get_for_model(model).pk,
                        "label": label,
                        "icon": config.icon
                        if config and config.icon
                        else "fa-solid fa-cube",
                        "model_label": str(model._meta.verbose_name_plural),
                        **(object_reference_metadata(obj) if kind == "object" else {}),
                    }
                )
            if len(items) >= 20:
                break
        if kind == "object":
            items.sort(key=reference_group_key)
    else:
        return JsonResponse({"error": "Unknown reference kind"}, status=400)
    return JsonResponse({"items": items[:20]})


def reference_group_key(item: dict[str, str | int]) -> tuple[str, int]:
    """Keep each content type together under a consistently ordered model heading."""
    return str(item.get("model_label", "")).casefold(), int(item["content_type_id"])
