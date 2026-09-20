"""Copy a listener's typed draft value into a compatible target."""

from django.db.models import QuerySet
from bloomerp.models.application_field import ApplicationField
from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorContext,
    BehaviorResult,
    CleanedConfigData,
    FieldValueUpdate,
)


def copy_targets(
    fields: QuerySet[ApplicationField], listener: ApplicationField | None
) -> QuerySet[ApplicationField]:
    """Offer fields with the same value type as the selected listener."""
    return fields.filter(field_type=listener.field_type) if listener else fields.none()


def copy_value(context: BehaviorContext, config: CleanedConfigData) -> BehaviorResult:
    """Return a value update for the declared target, without modifying the draft."""
    return BehaviorResult(
        values=(
            FieldValueUpdate(field=context.target_field, value=context.listener_value),
        )
    )


COPY_VALUE = BehaviorActionDefinition(
    id="copy_value",
    label="Copy value",
    description="Copy the listener value into a compatible target.",
    requires_target_field=True,
    get_target_fields=copy_targets,
    execute=copy_value,
)
