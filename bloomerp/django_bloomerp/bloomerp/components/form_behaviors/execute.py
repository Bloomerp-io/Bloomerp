"""HTTP adapter for authorized, side-effect-free behavior evaluation."""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError as SchemaError,
    model_validator,
)

from bloomerp.form_behaviors.execution import BehaviorExecutor
from bloomerp.models.forms.form import Form
from bloomerp.models.users.user_object_layout_preference import (
    UserObjectLayoutPreference,
)
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router


class ExecuteRequest(BaseModel):
    """Identify exactly one saved layout and the current unsaved event snapshot."""

    model_config = ConfigDict(extra="forbid")
    preference_id: str | int | None = None
    form_id: str | int | None = None
    object_id: str | int | None = None
    listener_field: str = Field(min_length=1)
    event: Literal["initial", "change"] = "change"
    revision: int = Field(ge=0)
    values: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_owner(self) -> ExecuteRequest:
        """Reject ambiguous requests rather than choosing a layout implicitly."""
        if (self.preference_id is None) == (self.form_id is None):
            raise ValueError("Supply exactly one preference_id or form_id.")
        return self


@router.register(
    path="components/form_behavior/execute/",
    url_name="components_form_behavior_execute",
)
@require_POST
def execute(request: HttpRequest) -> JsonResponse:
    """Load an authorized layout and translate execution results into JSON responses."""
    try:
        payload = ExecuteRequest.model_validate_json(request.body)
    except SchemaError:
        return JsonResponse(
            {"error": "Invalid behavior execution request."}, status=400
        )
    try:
        manager = UserPolicyManager(request.user)
        form_submission_access = False
        if payload.preference_id is not None:
            if not request.user.is_authenticated:
                raise PermissionDenied
            owner = get_object_or_404(
                UserObjectLayoutPreference.objects.select_related("content_type"),
                pk=payload.preference_id,
                user=request.user,
            )
        else:
            if payload.object_id is None:
                # Create drafts inherit the Form submission page's authentication
                # contract; evaluation is side-effect-free and layout-scoped.
                owner = get_object_or_404(
                    Form.objects.select_related("content_type"), pk=payload.form_id
                )
                if owner.requires_authentication and not request.user.is_authenticated:
                    raise PermissionDenied
                form_submission_access = True
            else:
                if not request.user.is_authenticated:
                    raise PermissionDenied
                owner = get_object_or_404(
                    manager.get_accessible_queryset(Form, "view"),
                    pk=payload.form_id,
                )
        model = owner.content_type.model_class()
        if model is None:
            raise ValidationError("Layout model is unavailable.")
        instance = None
        if payload.object_id is not None:
            # Check model capability before object lookup to preserve 403 semantics.
            if not manager.has_global_permission(model, "change"):
                raise PermissionDenied
            instance = get_object_or_404(
                manager.get_accessible_queryset(model, "change"), pk=payload.object_id
            )
        result = BehaviorExecutor(
            owner,
            request.user,
            instance=instance,
            form_submission_access=form_submission_access,
        ).evaluate(
            payload.listener_field,
            payload.values,
            event=payload.event,
        )
    except (SchemaError, ValidationError, ValueError, TypeError) as error:
        return JsonResponse(
            {"error": "Behavior evaluation failed.", "detail": str(error)}, status=400
        )
    return JsonResponse({"revision": payload.revision, **asdict(result)})
