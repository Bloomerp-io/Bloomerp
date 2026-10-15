"""Set a scalar date or datetime relative to the current local date or instant."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django import forms
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorContext,
    BehaviorResult,
    BehaviorUser,
    CleanedConfigData,
    FieldValueUpdate,
)
from bloomerp.form_behaviors.shared.temporal import (
    shift_temporal,
    temporal_fields,
    temporal_kind,
)
from bloomerp.form_behaviors.shared.write_policy import (
    WritePolicyField,
    should_write_value,
)
from bloomerp.models.application_field import ApplicationField


def set_relative_date_targets(
    fields: QuerySet[ApplicationField],
    listener: ApplicationField | None,
) -> QuerySet[ApplicationField]:
    """Offer only editable scalar date and datetime destinations."""
    return temporal_fields(fields)


def set_relative_date_config_form_factory(
    target: ApplicationField | None,
    listener: ApplicationField | None,
    request: HttpRequest | None = None,
) -> type[forms.Form]:
    """Build an integer offset editor whose unit follows the selected target."""
    if target is None:
        raise forms.ValidationError(_("Select a target field first."))
    kind = temporal_kind(target)
    if kind is None:
        raise forms.ValidationError(
            _("Select an editable scalar date or datetime target field.")
        )
    offset_label = _("Offset (days)") if kind == "date" else _("Offset (minutes)")
    offset_help = (
        _("Whole days relative to today in the current timezone. "
        "Use a positive number for later, a negative number for earlier, or zero for today.")
        if kind == "date"
        else _("Whole minutes relative to the current time. "
        "Use a positive number for later, a negative number for earlier, or zero for now.")
    )

    class SetRelativeDateForm(forms.Form):
        """Validate a signed integer offset and scalar replacement policy."""

        offset = forms.IntegerField(
            initial=0,
            label=offset_label,
            help_text=offset_help,
        )
        write_policy = WritePolicyField(
            label=_('Write policy'),
            allowed=("always", "if_empty"), default="always"
        )

        def clean(self) -> dict[str, Any]:
            """Retain the validated destination type without storing a unit option."""
            cleaned = super().clean()
            cleaned["temporal_kind"] = kind
            return cleaned

    return SetRelativeDateForm


def set_relative_date(
    context: BehaviorContext,
    config: CleanedConfigData,
    user: BehaviorUser,
) -> BehaviorResult:
    """Return a draft-only temporal update anchored to the current date or time."""
    if not should_write_value(context.target_value, config["write_policy"]):
        return BehaviorResult()
    anchor = (
        timezone.localdate() if config["temporal_kind"] == "date" else timezone.now()
    )
    result = shift_temporal(anchor, Decimal(config["offset"]))
    if result == context.target_value:
        return BehaviorResult()
    return BehaviorResult(
        values=(FieldValueUpdate(field=context.target_field, value=result),)
    )


SET_RELATIVE_DATE = BehaviorActionDefinition(
    id="set_relative_date",
    label=_("Set relative date"),
    description=(
        _("Set a date relative to today in whole days, or a datetime relative "
        "to now in whole minutes.")
    ),
    requires_target_field=True,
    execute=set_relative_date,
    config_form_factory=set_relative_date_config_form_factory,
    get_target_fields=set_relative_date_targets,
    group=_("Field values"),
)
