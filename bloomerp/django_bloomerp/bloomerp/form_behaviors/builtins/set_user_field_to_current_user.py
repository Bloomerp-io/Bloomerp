"""Set a user relation to the authenticated user evaluating the behavior."""

from django.db.models import QuerySet

from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorContext,
    BehaviorResult,
    BehaviorUser,
    CleanedConfigData,
    FieldValueUpdate,
)
from bloomerp.form_behaviors.shared.permissions import permission_denied_result
from bloomerp.models.application_field import ApplicationField


def user_field_targets(
    fields: QuerySet[ApplicationField],
    listener: ApplicationField | None,
) -> QuerySet[ApplicationField]:
    """Limit destination choices to fields backed by Bloomerp users."""
    return fields.filter(field_type=FIELD_TYPE_REGISTRY.USER_FIELD.id)


def set_user_field_to_current_user(
    context: BehaviorContext,
    config: CleanedConfigData,
    user: BehaviorUser,
) -> BehaviorResult:
    """Assign the authenticated user's identifier to the selected target field."""
    if not getattr(user, "is_authenticated", False) or user.pk is None:
        return permission_denied_result("an authenticated user is required")
    if context.target_value == user.pk:
        return BehaviorResult()
    return BehaviorResult(
        values=(FieldValueUpdate(field=context.target_field, value=user.pk),)
    )


SET_USER_FIELD_TO_CURRENT_USER = BehaviorActionDefinition(
    id="set_user_field_to_current_user",
    label="Set user field to current user",
    description="Set the selected user field to the authenticated user evaluating the form.",
    get_target_fields=user_field_targets,
    requires_target_field=True,
    execute=set_user_field_to_current_user,
    group="Field values",
)
