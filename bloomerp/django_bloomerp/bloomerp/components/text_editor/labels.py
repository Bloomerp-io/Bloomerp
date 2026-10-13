"""Create or edit shared labels using the centralized creator/admin rule."""

import re
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST
from bloomerp.models import Label
from bloomerp.router import router
from bloomerp.services.object_reference_services import can_change_label


@router.register(
    path="components/text_editor/labels", url_name="components_text_editor_labels"
)
@login_required
@require_POST
def save_label(request: HttpRequest) -> JsonResponse:
    """Let authenticated users create labels and creators or admins update them."""
    label_id = request.POST.get("label_id")
    if label_id:
        try:
            label_id = int(label_id)
            if label_id < 1:
                raise ValueError("Invalid label ID")
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid label ID"}, status=400)
    label = (
        get_object_or_404(Label, pk=label_id)
        if label_id
        else Label(created_by=request.user)
    )
    if label.pk and not can_change_label(request.user, label):
        return JsonResponse({"error": "Label permission denied"}, status=403)
    name = request.POST.get("name", "").strip()
    color = request.POST.get("color", label.color)
    if not name or len(name) > 100 or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        return JsonResponse(
            {"error": "Provide a label name and a hex color"}, status=400
        )
    label.name, label.color, label.updated_by = name, color, request.user
    try:
        with transaction.atomic():
            label.save()
    except IntegrityError:
        return JsonResponse(
            {"error": "A label with that name already exists"}, status=409
        )
    return JsonResponse(
        {
            "kind": "label",
            "target_id": str(label.pk),
            "label": label.name,
            "color": label.color,
        },
        status=200 if request.POST.get("label_id") else 201,
    )
