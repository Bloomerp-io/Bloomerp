"""Evaluate stored form behaviors against a validated, unsaved draft.

This module has no HTTP dependency and never saves model instances. It evaluates
one listener event in declaration order; dependency cascading remains separate.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from collections.abc import Set as AbstractSet
from copy import deepcopy
from dataclasses import replace
from typing import Any, Literal

from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Model, Q
from django.http import HttpRequest

from bloomerp.field_types.utils.form_field_factories import build_form_field
from bloomerp.filters.compiler import resolve_condition
from bloomerp.filters.definition import Filter
from bloomerp.form_behaviors.definition import (
    BehaviorConfig,
    BehaviorContext,
    BehaviorFieldReference,
    BehaviorMessage,
    BehaviorResult,
    BehaviorUser,
    FieldStateUpdate,
    FieldValueUpdate,
)
from bloomerp.form_behaviors.registry import ACTION_REGISTRY
from bloomerp.form_behaviors.utils import clean_action_config
from bloomerp.form_fields.structured_value import serialize_form_value
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.forms.form import Form
from bloomerp.models.users.user_object_layout_preference import (
    UserObjectLayoutPreference,
)
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.services.preference_services import PreferenceManager

LayoutOwner = Form | UserObjectLayoutPreference


def iter_config_field_references(
    value: Any,
) -> Iterator[BehaviorFieldReference]:
    """Yield permission-aware field references from nested cleaned configuration."""
    if isinstance(value, BehaviorFieldReference):
        yield value
        return
    if isinstance(value, ApplicationField):
        yield BehaviorFieldReference(field=value)
        return
    if isinstance(value, Mapping):
        for nested_value in value.values():
            yield from iter_config_field_references(nested_value)
        return
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for nested_value in value:
            yield from iter_config_field_references(nested_value)
        return
    if isinstance(value, AbstractSet):
        for nested_value in value:
            yield from iter_config_field_references(nested_value)


class BehaviorExecutor:
    """Authorize a layout and evaluate actions using its model's field contracts."""

    def _can_access_preference(self, owner: UserObjectLayoutPreference) -> bool:
        """Return whether the user owns or currently receives the preference."""
        return (
            PreferenceManager(self.user)
            .get_available(UserObjectLayoutPreference)
            .filter(Q(pk=owner.pk) | Q(source_object_id=owner.pk))
            .exists()
        )

    def __init__(
        self,
        owner: LayoutOwner,
        user: BehaviorUser,
        *,
        instance: Model | None = None,
        form_submission_access: bool = False,
        request: HttpRequest | None = None,
    ) -> None:
        """Bind request/user context, an owner, and layout-scoped field access.

        ``form_submission_access`` mirrors the fields deliberately exposed by a
        Form submission page. It is limited to unsaved create drafts and never
        grants access to user preferences or persisted target objects.
        """
        self.owner, self.user, self.instance = owner, user, instance
        self.request = request
        self.manager = UserPolicyManager(user)
        self.form_submission_access = form_submission_access
        if form_submission_access:
            if not isinstance(owner, Form) or instance is not None:
                raise ValidationError(
                    "Form submission access requires an unsaved Form draft."
                )
            if owner.requires_authentication and not user.is_authenticated:
                raise PermissionDenied
        else:
            if not user.is_authenticated:
                raise PermissionDenied
            if isinstance(owner, UserObjectLayoutPreference):
                if not self._can_access_preference(owner):
                    raise PermissionDenied
            elif isinstance(owner, Form):
                if not self.manager.has_access_to_object(owner, "view"):
                    raise PermissionDenied
            else:
                raise ValidationError("Unsupported layout owner.")
        self.model = owner.content_type.model_class()
        if self.model is None:
            raise ValidationError("Layout model is unavailable.")
        permission = "add" if instance is None else "change"
        if form_submission_access:
            readable = ApplicationField.objects.filter(content_type=owner.content_type)
            writable = readable
        elif instance is not None:
            if not self.manager.has_global_permission(self.model, permission):
                raise PermissionDenied
            if not isinstance(
                instance, self.model
            ) or not self.manager.has_access_to_object(instance, permission):
                raise PermissionDenied
            readable = self.manager.get_accessible_fields_for_object(instance, "view")
            writable = self.manager.get_accessible_fields_for_object(
                instance, permission
            )
        else:
            if not self.manager.has_global_permission(self.model, permission):
                raise PermissionDenied
            readable = self.manager.get_accessible_fields(self.model, "view")
            writable = self.manager.get_accessible_fields(self.model, permission)
        fields = list(ApplicationField.objects.filter(content_type=owner.content_type))
        by_reference = {
            key: field for field in fields for key in (field.field, str(field.pk))
        }
        self.items = {}
        for row in owner.layout_obj.rows:
            for item in row.items:
                field = by_reference.get(str(item.id))
                if field is not None:
                    if field.field in self.items:
                        raise ValidationError("Each layout field must occur once.")
                    self.items[field.field] = item
        self.readable = readable.filter(field__in=self.items)
        self.writable = writable.filter(field__in=self.items)
        self.read_fields = {field.field: field for field in self.readable}
        self.write_fields = {field.field: field for field in self.writable}

    def _clean_value(self, field: ApplicationField, value: Any) -> Any:
        """Coerce field values without requiring completion of the whole draft."""
        layout_config = (
            self.items[field.field].config
            if field.content_type_id == self.owner.content_type_id
            and field.field in self.items
            else {}
        )
        form_field = build_form_field(field, layout_config=layout_config)
        if form_field is None:
            raise ValidationError(
                f"Field '{field.field}' has no editable value contract."
            )
        if field.get_field_type().id == "OneToManyField":
            return self._clean_rows(field, value)
        form_field.required = False
        if (
            isinstance(form_field, forms.CharField)
            and not isinstance(form_field, forms.JSONField)
            and isinstance(value, (dict, list, tuple))
        ):
            raise ValidationError(f"Field '{field.field}' requires a scalar value.")
        if isinstance(form_field, forms.BooleanField) and value not in (
            None,
            "",
            True,
            False,
            0,
            1,
            "0",
            "1",
            "true",
            "false",
            "True",
            "False",
        ):
            raise ValidationError(f"Field '{field.field}' requires a boolean value.")
        if (
            isinstance(form_field, forms.ModelChoiceField)
            and not self.form_submission_access
        ):
            form_field.queryset = self.manager.get_accessible_queryset(
                form_field.queryset.model, "view"
            )
        if isinstance(form_field, forms.JSONField):
            value = json.dumps(value)
        cleaned = form_field.clean(value)
        if field.get_field_type().id == "WeekField" and cleaned is not None:
            return str(cleaned)
        if isinstance(cleaned, Model):
            return cleaned.pk
        return cleaned

    def _clean_rows(self, field: ApplicationField, value: Any) -> list[dict[str, Any]]:
        """Validate partial collection rows without invoking persistence or full child forms.

        Public Form submissions may evaluate new rows from their exposed create
        contract. Persisted row identities remain restricted to authorized object
        edits until candidate child-row policies can be enforced.
        """
        if not self.user.is_superuser and not self.form_submission_access:
            raise PermissionDenied(
                "Collection execution awaits child-row permission checks."
            )
        if value is None:
            return []
        if not isinstance(value, list) or len(value) > 1000:
            raise ValidationError("Collections require at most 1000 row objects.")
        widget = field.get_widget(layout_config=self.items[field.field].config)
        columns = {column.field: column for column in widget.get_columns()}
        related_model = field.get_related_model()
        parent_field = field._get_model_field().field.name
        rows, seen = [], set()
        for row in value:
            if not isinstance(row, dict) or set(row) - (
                columns.keys() | {"id", "DELETE"}
            ):
                raise ValidationError("Invalid collection row columns.")
            cleaned = {}
            object_id = row.get("id")
            if object_id not in (None, ""):
                if (
                    self.form_submission_access
                    or self.instance is None
                    or str(object_id) in seen
                ):
                    raise ValidationError("Invalid or duplicate related row identity.")
                if not related_model._default_manager.filter(
                    pk=object_id, **{parent_field: self.instance}
                ).exists():
                    raise ValidationError("Related row does not belong to this object.")
                seen.add(str(object_id))
                cleaned["id"] = str(object_id)
            if "DELETE" in row:
                cleaned["DELETE"] = forms.BooleanField(required=False).clean(
                    row["DELETE"]
                )
            for name, raw in row.items():
                if name in {"id", "DELETE"}:
                    continue
                if columns[name].get_field_type().id == "OneToManyField":
                    raise ValidationError("Nested collections are not supported.")
                cleaned[name] = self._clean_value(columns[name], raw)
            rows.append(cleaned)
        return rows

    def _resolve_related_values(
        self, source: ApplicationField, accessor: ApplicationField,
        identities: tuple[Any, ...],
    ) -> Mapping[str, Any]:
        """Read one related column in bulk, enforcing record and per-record field access."""
        model = source.get_related_model()
        if model is None or accessor.get_model() is not model:
            raise ValidationError("Accessor must belong to the source relation's model.")
        if self.form_submission_access:
            records = list(model._default_manager.filter(pk__in=identities))
        else:
            if not self.manager.has_global_permission(model, "view"):
                raise PermissionDenied
            records = list(
                self.manager.get_accessible_queryset(model, "view").filter(
                    pk__in=identities
                )
            )
        if {str(record.pk) for record in records} != {str(identity) for identity in identities}:
            raise PermissionDenied("A related source record is unavailable.")
        values: dict[str, Any] = {}
        model_field = model._meta.get_field(accessor.field)
        if not model_field.concrete or model_field.many_to_many:
            raise ValidationError("Accessor must expose a single stored value.")
        for record in records:
            if (
                not self.form_submission_access
                and not self.manager.get_accessible_fields_for_object(
                    record, "view"
                ).filter(pk=accessor.pk).exists()
            ):
                raise PermissionDenied("The related source field is unavailable.")
            values[str(record.pk)] = getattr(record, model_field.attname)
        return values

    def _matches(self, group: Filter, values: Mapping[str, Any]) -> bool:
        """Evaluate all group predicates with their registered Python lookup implementations."""
        matches = []
        for condition in group.conditions:
            name = condition.field_path
            if name not in self.read_fields or name not in values:
                raise ValidationError("Condition field is unavailable in this draft.")
            _, _, lookup, expected = resolve_condition(condition, model=self.model)
            evaluator = lookup.get_python_evaluator()
            if evaluator is None:
                raise ValidationError("Condition lookup cannot evaluate draft values.")
            matches.append(evaluator(values[name], expected))
        return all(matches) if group.connector == "AND" else any(matches)

    def _add_draft_value(
        self,
        draft: dict[str, Any],
        values: Mapping[str, Any],
        field_name: str,
    ) -> None:
        """Clean one declared draft dependency exactly once."""
        if field_name in draft:
            return
        if field_name not in self.read_fields or field_name not in values:
            raise ValidationError(
                f"Field '{field_name}' is unavailable in this draft."
            )
        draft[field_name] = self._clean_value(
            self.read_fields[field_name], deepcopy(values[field_name])
        )

    def evaluate(
        self,
        listener_field: str,
        values: Mapping[str, Any],
        *,
        event: Literal["initial", "change"] = "change",
    ) -> BehaviorResult:
        """Return a complete validated batch, leaving the input and database untouched."""
        if event not in {"initial", "change"}:
            raise ValidationError("Unknown behavior event.")
        if (
            listener_field not in self.read_fields
            or not set(values) <= self.read_fields.keys()
        ):
            raise PermissionDenied
        if listener_field not in values:
            raise ValidationError("Listener field value is missing from the draft.")
        listener = self.read_fields[listener_field]
        draft: dict[str, Any] = {}
        self._add_draft_value(draft, values, listener_field)
        config = BehaviorConfig.model_validate(
            self.items[listener_field].config.get("behaviors") or {}
        )
        updates, states, messages = [], [], []
        for behavior in config.behaviors:
            if not behavior.enabled or event not in behavior.events:
                continue
            for group in behavior.conditions:
                for condition in group.conditions:
                    self._add_draft_value(
                        draft, values, condition.field_path
                    )
            # Evaluate every group, including groups after one that does not match.
            group_matches = [
                self._matches(group, draft) for group in behavior.conditions
            ]
            if not all(group_matches):
                continue
            for configured in behavior.actions:
                action = ACTION_REGISTRY.get(configured.action)
                if action is None:
                    raise ValidationError(f"Unknown action: {configured.action}.")
                if (
                    not action.get_listener_fields(self.readable)
                    .filter(pk=listener.pk)
                    .exists()
                ):
                    raise ValidationError("Action is not applicable to this listener.")
                target = (
                    self.write_fields.get(configured.target_field)
                    if configured.target_field
                    else None
                )
                if configured.target_field and target is None:
                    raise PermissionDenied
                if action.requires_target_field and target is None:
                    raise ValidationError("Action requires a target field.")
                if target is not None:
                    self._add_draft_value(draft, values, target.field)
                    if (
                        not action.get_target_fields(self.writable, listener)
                        .filter(pk=target.pk)
                        .exists()
                    ):
                        raise ValidationError(
                            "Action is not applicable to this target."
                        )
                cleaned = clean_action_config(
                    action,
                    listener,
                    target,
                    configured.config,
                    request=self.request,
                )
                for reference in iter_config_field_references(cleaned):
                    field = reference.field
                    if field.content_type_id == listener.content_type_id:
                        available_fields = (
                            self.read_fields
                            if reference.permission == "view"
                            else self.write_fields
                        )
                        if field.field not in available_fields:
                            raise PermissionDenied
                        self._add_draft_value(draft, values, field.field)
                    elif (
                        not self.form_submission_access
                        and not self.manager.has_field_permission(
                            field, reference.permission
                        )
                    ):
                        raise PermissionDenied
                result = action.execute(
                    BehaviorContext(
                        values=deepcopy(draft),
                        listener_field=listener.field,
                        target_field=target.field if target else "",
                        resolve_related_values=self._resolve_related_values,
                    ),
                    cleaned,
                    self.user,
                )
                if not isinstance(result, BehaviorResult):
                    raise ValidationError("Action must return a BehaviorResult.")
                if not all(
                    isinstance(items, tuple)
                    for items in (result.values, result.states, result.messages)
                ):
                    raise ValidationError("Action result collections must be tuples.")
                declared_update_field = target or self.write_fields.get(listener.field)
                for update in result.values:
                    if (
                        not isinstance(update, FieldValueUpdate)
                        or declared_update_field is None
                        or update.field != declared_update_field.field
                    ):
                        raise ValidationError(
                            "Action returned an undeclared value target."
                        )
                    draft[update.field] = self._clean_value(
                        declared_update_field, update.value,
                    )
                    updates.append(
                        replace(update, value=serialize_form_value(draft[update.field]))
                    )
                for state in result.states:
                    if (
                        not isinstance(state, FieldStateUpdate)
                        or declared_update_field is None
                        or state.field != declared_update_field.field
                        or (
                            state.visible is not None
                            and not isinstance(state.visible, bool)
                        )
                        or not isinstance(state.disabled, bool)
                    ):
                        raise ValidationError(
                            "Action returned an invalid state target."
                        )
                    states.append(state)
                for message in result.messages:
                    if (
                        not isinstance(message, BehaviorMessage)
                        or message.type not in {"info", "warning", "danger", "success"}
                        or not isinstance(message.message, str)
                    ):
                        raise ValidationError("Action returned an invalid message.")
                    messages.append(message)
        return BehaviorResult(
            values=tuple(updates), states=tuple(states), messages=tuple(messages)
        )
