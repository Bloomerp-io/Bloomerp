"""Render one action's configuration fields inside the display-options form."""

import json
import re

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from bloomerp.components.objects.details.field_display_options import (
    _get_item_config,
    _get_layout_config_target,
    _user_can_configure_field,
)
from bloomerp.form_behaviors.registry import ACTION_REGISTRY
from bloomerp.form_behaviors.utils import action_config_form
from bloomerp.models.application_field import ApplicationField
from bloomerp.router import router


@router.register(
    path="components/form_behavior/render_action_config_form",
    url_name="components_render_action_form",
)
@login_required
@require_GET
def render_action_config_form(request: HttpRequest) -> HttpResponse:
    """Return a scoped, uniquely prefixed fragment without a nested form element."""
    try:
        scope = _get_layout_config_target(request)
    except (ValidationError, ValueError, TypeError):
        return JsonResponse({"error": "Invalid layout context."}, status=400)
    if scope is None:
        return JsonResponse({"error": "A layout context is required."}, status=400)
    listener_id = request.GET.get("listener_field_id", "")
    if not listener_id.isdigit():
        return JsonResponse(
            {"error": "A valid listener field is required."}, status=400
        )
    listener = get_object_or_404(
        ApplicationField,
        pk=listener_id,
        content_type=scope.content_type,
    )
    if not _user_can_configure_field(request, scope, listener):
        raise PermissionDenied
    action = ACTION_REGISTRY.get(request.GET.get("action_id", ""))
    if action is None:
        raise Http404("Action does not exist.")
    available = ApplicationField.objects.filter(content_type=scope.content_type)
    if not action.get_listener_fields(available).filter(pk=listener.pk).exists():
        raise PermissionDenied
    target_name = request.GET.get("target_field", "")
    target = None
    if target_name:
        target = get_object_or_404(
            action.get_target_fields(available, listener), field=target_name
        )
        if not _user_can_configure_field(request, scope, target):
            raise PermissionDenied
    try:
        config = json.loads(request.GET.get("config", "{}"))
        if not isinstance(config, dict):
            raise ValidationError("Configuration must be an object.")
        prefix = request.GET.get("prefix", "")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,150}", prefix):
            raise ValidationError("A valid editor prefix is required.")
        form = action_config_form(
            action,
            listener,
            target,
            config,
            prefix=prefix,
            request=request,
            listener_layout_config=_get_item_config(
                scope.layout_object,
                listener,
            ),
        )
        entries = []
        for name, field in form.fields.items():
            kind = "json" if isinstance(field, forms.JSONField) else "value"
            entries.append({
                "name": name, "kind": kind, "field": form[name],
                "refresh": name in getattr(form, "refresh_fields", ()),
            })
    except (ValueError, ValidationError) as error:
        return JsonResponse({"error": str(error)}, status=400)
    return render(
        request,
        "components/form_behavior/render_action_config_form.html",
        {"entries": entries},
    )
