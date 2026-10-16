"""Optional recipient suggestions from readable email fields on searchable models."""

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import Model
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
from bloomerp.models.application_field import ApplicationField
from bloomerp.router import router
from bloomerp.services.search_services import SearchManager


@router.register(
    path="components/communication/emails/search_email_address",
    url_name="components_search_email_address",
)
@login_required
@require_GET
def search_email_address(request: HttpRequest) -> JsonResponse:
    """Return bounded, deduplicated email suggestions respecting row and field access."""
    query = request.GET.get("q", "").strip()
    if len(query) < 2 or len(query) > 200:
        return JsonResponse({"suggestions": []})

    fields_by_model: dict[type[Model], list[str]] = {}
    for field in ApplicationField.objects.filter(
        field_type=FIELD_TYPE_REGISTRY.EMAIL_FIELD.id,
    ).select_related("content_type").order_by("pk"):
        model = field.content_type.model_class()
        if model is not None:
            fields_by_model.setdefault(model, []).append(field.field)

    manager = SearchManager(request.user)
    objects = manager.search_objects(query, models=fields_by_model, per_model_limit=10, total_limit=40)
    suggestions: list[dict[str, str]] = []
    seen: set[str] = set()
    items = objects.items
    if request.GET.get("calendar_users") == "1":
        user_model = get_user_model()
        items = [obj for obj in items if isinstance(obj, user_model)] + [obj for obj in items if not isinstance(obj, user_model)]
    for obj in items:
        readable = set(manager.permission_manager.get_accessible_fields_for_object(
            obj, "view",
        ).values_list("field", flat=True))
        for field_name in fields_by_model[type(obj)]:
            if field_name not in readable:
                continue
            address = getattr(obj, field_name, None)
            if not isinstance(address, str):
                continue
            address = address.strip()
            if not address and request.GET.get("calendar_users") == "1" and isinstance(obj, get_user_model()) and obj.is_active:
                address = f"user:{obj.pk}"
                suggestions.append({"email": address, "label": str(obj._meta.verbose_name), "user_id": str(obj.pk), "display_name": str(obj)})
                if len(suggestions) == 10:
                    return JsonResponse({"suggestions": suggestions})
                continue
            try:
                validate_email(address)
            except ValidationError:
                continue
            if address.casefold() in seen:
                continue
            seen.add(address.casefold())
            suggestion = {"email": address, "label": str(obj._meta.verbose_name)}
            if request.GET.get("calendar_users") == "1" and isinstance(obj, get_user_model()) and obj.is_active:
                suggestion["user_id"] = str(obj.pk)
                suggestion["display_name"] = str(obj)
            suggestions.append(suggestion)
            if len(suggestions) == 10:
                return JsonResponse({"suggestions": suggestions})
    return JsonResponse({"suggestions": suggestions})
