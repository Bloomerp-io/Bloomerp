"""Canonical write-policy form field and scalar decision helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal, DecimalException
from typing import Any, Literal

from django import forms
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

from bloomerp.models.application_field import ApplicationField

WritePolicyId = Literal["always", "if_empty", "if_empty_or_zero", "replace"]

WRITE_POLICY_LABELS: Mapping[WritePolicyId, Promise] = {
    "always": _("Always"),
    "if_empty": _("Only when empty"),
    "if_empty_or_zero": _("When empty or zero"),
    "replace": _("Replace"),
}


class WritePolicyField(forms.TypedChoiceField):
    """Expose an action-specific subset of canonical, stable write-policy IDs."""

    def __init__(
        self,
        *,
        allowed: Iterable[WritePolicyId],
        default: WritePolicyId,
        **kwargs: Any,
    ) -> None:
        """Build strict choices and map omitted legacy values to the action default."""
        allowed_ids = tuple(allowed)
        if not allowed_ids:
            raise ValueError("WritePolicyField requires at least one allowed policy.")
        if any(policy not in WRITE_POLICY_LABELS for policy in allowed_ids):
            raise ValueError("WritePolicyField received an unknown policy ID.")
        if default not in allowed_ids:
            raise ValueError(
                "WritePolicyField default must be in its allowed policies."
            )
        kwargs.setdefault(
            "choices",
            tuple((policy, WRITE_POLICY_LABELS[policy]) for policy in allowed_ids),
        )
        kwargs.setdefault("required", False)
        kwargs.setdefault("initial", default)
        kwargs.setdefault("empty_value", default)
        kwargs.setdefault("coerce", str)
        super().__init__(**kwargs)


def write_value_is_empty(
    value: Any,
    field: ApplicationField | None = None,
) -> bool:
    """Recognize generic blanks or a concrete field's accepted empty inputs."""
    if field is None:
        return value is None or value == ""
    form_field = field.get_form_field()
    if form_field is None:
        raise forms.ValidationError(f"Field '{field.field}' is not editable.")
    return value in form_field.empty_values


def write_value_is_zero(value: Any) -> bool:
    """Recognize finite normalized numeric zero without treating booleans as numbers."""
    if isinstance(value, bool):
        return False
    try:
        converted = Decimal(str(value).strip())
    except (DecimalException, TypeError, ValueError):
        return False
    return converted.is_finite() and converted == 0


def should_write_value(
    value: Any,
    write_policy: str,
    *,
    field: ApplicationField | None = None,
) -> bool:
    """Apply canonical scalar always, empty-only, or empty-or-zero semantics."""
    if write_policy == "always":
        return True
    if write_value_is_empty(value, field):
        return True
    if write_policy == "if_empty":
        return False
    if write_policy == "if_empty_or_zero":
        return write_value_is_zero(value)
    raise forms.ValidationError("Unknown scalar write policy.")
