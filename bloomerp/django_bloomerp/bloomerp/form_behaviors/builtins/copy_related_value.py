"""Copy a listener's typed draft value into a compatible target."""

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
from bloomerp.form_behaviors.shared import write_policy
from bloomerp.form_behaviors.shared.permissions import permission_denied_result
from bloomerp.models.application_field import ApplicationField
from django import forms

from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager


def copy_related_values(
    context: BehaviorContext,
    config: CleanedConfigData,
    user: BehaviorUser,
) -> BehaviorResult:
    """Return a value update for the declared target, without modifying the draft."""
    related_field = config.get("related_field")
    policy_manager = UserPolicyManager(user)
    related_model = ApplicationField.get_for_model(
        context.model
    ).get(
        field=context.listener_field
    ).related_model.model_class()
    
    try:
        obj = related_model.objects.get(
            id=context.listener_value
        )
    except:
        return BehaviorResult()
    
    if not policy_manager.has_access_to_object(
        obj,
        fields=[related_field],
        permissions=[BloomerpPermission.VIEW]
    ):
        return permission_denied_result(f"You don't have permission to view {related_field.title}")

    if not write_policy.should_write_value(context.target_value, config.get("write_policy")):
        return BehaviorResult()
    
    return BehaviorResult(
        values=(
            FieldValueUpdate(field=context.target_field, value=getattr(obj, related_field.field)),
        )
    )


COPY_RELATED_VALUE = BehaviorActionDefinition(
    id="copy_related_value",
    label="Copy Related Value",
    description="Copy the listener's related value into a compatible target.",
    requires_target_field=True,
    execute=copy_related_values,
    get_listener_fields=lambda fields: fields.filter(
        field_type__in=[
            FIELD_TYPE_REGISTRY.FOREIGN_KEY.id,
            FIELD_TYPE_REGISTRY.ONE_TO_ONE_FIELD.id,
        ]
    ),
    config_form_factory=lambda target, listener, request: type(
        "CopyRelatedValueForm",
        (forms.Form, ),
        {
            "related_field" : forms.ModelChoiceField(
                queryset=ApplicationField.get_for_model(listener.related_model.model_class()).filter(
                    field_type=target.field_type
                ),
                help_text="The related attribute on the listener to copy into the target field"
            ),
            "write_policy" : write_policy.WritePolicyField(
                allowed=["always", "if_empty"],
                default="always"
            )
        }
    )
)
