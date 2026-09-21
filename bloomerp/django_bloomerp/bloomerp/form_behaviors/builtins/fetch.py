"""Fetch authorized source records into scalar fields or collection draft rows."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from django import forms
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db.models import Model, QuerySet
from django.http import HttpRequest
from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
from bloomerp.filters.definition import Filter, Filters
from bloomerp.filters.manager import ModelFilterManager
from bloomerp.form_behaviors.builtins.set_o2m_value import (
    collection_rows,
    compatible_columns,
    value_columns,
)
from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorContext,
    BehaviorFieldReference,
    BehaviorResult,
    BehaviorUser,
    CleanedConfigData,
    FieldValueUpdate,
)
from bloomerp.form_behaviors.shared.permissions import permission_denied_result
from bloomerp.form_behaviors.shared.write_policy import should_write_value
from bloomerp.form_fields.structured_value import serialize_form_value
from bloomerp.models.application_field import ApplicationField
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.widgets.code_editor_widget import CodeEditorWidget
from bloomerp.widgets.filter_widget import FilterWidget
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget

FILTERS_ADAPTER = TypeAdapter(list[Filter])
VALUE_REFERENCE = re.compile(
    r"^\s*\{\{\s*(object|row)\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}\s*$"
)
MAX_FETCH_ROWS = 1000
DELETED = (True, "true", "True", "1", "on", "yes")


def single_value_fields(
    fields: QuerySet[ApplicationField],
) -> QuerySet[ApplicationField]:
    """Exclude collection relations from a one-value destination."""
    return fields.exclude(
        field_type__in=(
            FIELD_TYPE_REGISTRY.MANY_TO_MANY_FIELD.id,
            FIELD_TYPE_REGISTRY.ONE_TO_MANY_FIELD.id,
        )
    )


def _content_type_from_initial(value: Any) -> ContentType | None:
    """Resolve a source content type by instance, ID, or portable model label."""
    if isinstance(value, ContentType):
        return value
    if isinstance(value, str) and "." in value:
        app_label, model = value.split(".", 1)
        return ContentType.objects.filter(app_label=app_label, model=model.lower()).first()
    try:
        return ContentType.objects.filter(pk=value).first()
    except (TypeError, ValueError):
        return None


class ContentTypeChoiceField(forms.ModelChoiceField):
    """Accept a stable app-label and model name in declarative fetch actions."""

    def clean(self, value: Any) -> ContentType | None:
        """Convert a portable model label before normal choice validation."""
        if isinstance(value, str) and "." in value:
            content_type = _content_type_from_initial(value)
            if content_type is None:
                raise forms.ValidationError("Select a valid source model.")
            value = content_type.pk
        return super().clean(value)


def parse_filters(value: Any) -> Filters:
    """Validate portable filter JSON against the shared filter schema."""
    if value in (None, "", []):
        return []
    try:
        return FILTERS_ADAPTER.validate_python(value)
    except PydanticValidationError as error:
        raise forms.ValidationError("Select valid matching filters.") from error


def resolve_filter_values(
    filters: Filters,
    *,
    object_values: Mapping[str, Any],
    row_values: Mapping[str, Any] | None = None,
) -> Filters:
    """Resolve exact draft placeholders while retaining their native value types."""
    resolved: list[Filter] = []
    sources = {"object": object_values, "row": row_values or {}}
    for group in filters:
        conditions = []
        for condition in group.conditions:
            value = condition.value
            match = VALUE_REFERENCE.fullmatch(value) if isinstance(value, str) else None
            if match is not None:
                scope, field_name = match.groups()
                if field_name not in sources[scope]:
                    raise forms.ValidationError(
                        f"The filter references unavailable {scope} field '{field_name}'."
                    )
                value = sources[scope][field_name]
            conditions.append(condition.model_copy(update={"value": value}))
        resolved.append(group.model_copy(update={"conditions": conditions}))
    return resolved


def filter_value_references(filters: Filters) -> set[tuple[str, str]]:
    """Collect object and row placeholders used by the configured filters."""
    references: set[tuple[str, str]] = set()
    for group in filters:
        for condition in group.conditions:
            value = condition.value
            match = VALUE_REFERENCE.fullmatch(value) if isinstance(value, str) else None
            if match is not None:
                references.add((match.group(1), match.group(2)))
    return references


def resolve_behavior_field_references(
    filters: Filters,
    *,
    object_model: type[Model],
    row_model: type[Model] | None = None,
    allowed_row_fields: QuerySet[ApplicationField] | None = None,
) -> tuple[BehaviorFieldReference, ...]:
    """Declare filter placeholders so the executor loads their draft dependencies."""
    references: list[BehaviorFieldReference] = []
    for scope, field_name in sorted(filter_value_references(filters)):
        model = object_model if scope == "object" else row_model
        candidates = (
            allowed_row_fields
            if scope == "row" and allowed_row_fields is not None
            else ApplicationField.get_for_model(model)
            if model is not None
            else ApplicationField.objects.none()
        )
        field = candidates.filter(field=field_name).first()
        if field is None:
            raise forms.ValidationError(
                f"The filter references unknown {scope} field '{field_name}'."
            )
        references.append(BehaviorFieldReference(field=field))
    return tuple(references)


def rendered_value_columns(target: ApplicationField) -> QuerySet[ApplicationField]:
    """Return writable child columns actually rendered by the target widget."""
    related_model = target.get_related_model()
    if related_model is None:
        return ApplicationField.objects.none()
    layout_config = getattr(target, "_behavior_layout_config", {})
    rendered_ids = [
        column.pk
        for column in target.get_widget(layout_config=layout_config).get_columns()
    ]
    return value_columns(related_model).filter(pk__in=rendered_ids)


def _source_fields(model: type[Model]) -> QuerySet[ApplicationField]:
    """Return stored source values suitable for copying to a destination."""
    return single_value_fields(value_columns(model))


def _ordered_records(
    *,
    content_type: ContentType,
    source_fields: tuple[ApplicationField, ...],
    filters: Filters,
    fetch: str,
    order_by: ApplicationField | None,
    user: BehaviorUser,
) -> list[Model] | BehaviorResult:
    """Query only accessible records and verify every selected source field."""
    model = content_type.model_class()
    if model is None or any(
        field.content_type_id != content_type.pk for field in source_fields
    ):
        raise forms.ValidationError("The configured source model is unavailable.")
    permission_fields = source_fields + ((order_by,) if order_by is not None else ())
    manager = UserPolicyManager(user)
    try:
        if any(
            not manager.has_field_permission(field, "view")
            for field in permission_fields
        ):
            raise PermissionDenied
        manager.validate_filters(model, filters)
        queryset = manager.get_accessible_queryset(model, "view")
        if filters:
            queryset = ModelFilterManager(model).apply(filters, queryset=queryset)
        order_field = (
            model._meta.get_field(order_by.field).attname
            if order_by is not None
            else model._meta.pk.name
        )
        order_fields = [order_field]
        if order_field != model._meta.pk.name:
            order_fields.append(model._meta.pk.name)
        if fetch == "last":
            order_fields = [f"-{field_name}" for field_name in order_fields]
        queryset = queryset.order_by(*order_fields)
        records = list(
            queryset[: MAX_FETCH_ROWS + 1] if fetch == "all" else queryset[:1]
        )
        if len(records) > MAX_FETCH_ROWS:
            raise forms.ValidationError("The lookup matched more than 1000 rows.")
        for record in records:
            allowed_ids = set(
                manager.get_accessible_fields_for_object(record, "view")
                .filter(pk__in=[field.pk for field in permission_fields])
                .values_list("pk", flat=True)
            )
            if any(field.pk not in allowed_ids for field in permission_fields):
                raise PermissionDenied
    except PermissionDenied:
        return permission_denied_result("you cannot read the configured lookup data")
    return records


def _record_value(record: Model, field: ApplicationField) -> Any:
    """Serialize a stored scalar or relation identity without loading its object."""
    model_field = record._meta.get_field(field.field)
    if not model_field.concrete or model_field.many_to_many:
        raise forms.ValidationError(
            "The configured source field is not a stored value."
        )
    return serialize_form_value(getattr(record, model_field.attname))


def fetch_config_form_factory(
    target: ApplicationField | None,
    listener: ApplicationField | None,
    request: HttpRequest | None = None,
) -> type[forms.Form]:
    """Build one editor with fields appropriate to its target and collection mode."""
    if target is None:
        raise forms.ValidationError("Select a target field first.")
    is_collection = target.field_type == FIELD_TYPE_REGISTRY.ONE_TO_MANY_FIELD.id
    target_columns = (
        rendered_value_columns(target)
        if is_collection
        else ApplicationField.objects.none()
    )

    class FetchForm(forms.Form):
        """Configure scalar, bulk-populate, or existing-row fetch behavior."""

        refresh_fields = ("mode", "model", "target_column")
        mode = forms.ChoiceField(
            choices=(
                ("populate", "Populate collection"),
                ("per_row", "Fetch for each existing row"),
            ),
            required=False,
        )
        model = ContentTypeChoiceField(
            queryset=ContentType.objects.all(),
            label="Source model",
            widget=ForeignFieldWidget(
                model=ContentType, attrs={"class": "input w-full"}
            ),
        )
        filters = forms.JSONField(
            required=False,
            widget=forms.HiddenInput(),
            help_text="Use {{ object.field }} or, in per-row mode, {{ row.column }}.",
        )
        fetch = forms.ChoiceField(
            choices=(("first", "First"), ("last", "Last"), ("all", "All"))
        )
        order_by = forms.ModelChoiceField(
            queryset=ApplicationField.objects.none(),
            required=False,
            label="Order by",
            help_text="Defaults to record ID; first/last use this field with ID as a tie-breaker.",
        )
        column = forms.ModelChoiceField(
            queryset=ApplicationField.objects.none(),
            required=False,
            label="Source column",
        )
        target_column = forms.ModelChoiceField(
            queryset=target_columns,
            required=False,
            label="Target column",
        )
        column_mappings = forms.JSONField(
            required=False,
            label="Column mappings",
            help_text='JSON object mapping target columns to source columns, for example {"quantity": "quantity"}.',
            widget=CodeEditorWidget(
                language="json"
            )
        )
        write_policy = forms.ChoiceField(required=False)

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            """Scope dependent choices and hide controls irrelevant to this mode."""
            super().__init__(*args, **kwargs)
            mode = self.initial.get("mode") or "populate"
            if not is_collection:
                self.fields.pop("mode")
                mode = "value"
            elif mode not in {"populate", "per_row"}:
                mode = "populate"
            if is_collection:
                self.initial["mode"] = mode
            if mode == "populate":
                self.fields["fetch"].choices = (("all", "All matching records"),)
                self.fields["write_policy"].choices = (
                    ("if_empty", "Only when the collection has no active rows"),
                    ("replace_unsaved", "Replace unsaved rows only"),
                )
                self.fields["write_policy"].initial = "if_empty"
                for field_name in ("column", "target_column"):
                    self.fields[field_name].widget = forms.HiddenInput()
                    self.initial[field_name] = None
                    self.fields[field_name].disabled = True
            else:
                self.fields["fetch"].choices = (("first", "First"), ("last", "Last"))
                self.fields["write_policy"].choices = (
                    ("always", "Always"),
                    ("if_empty", "Only when empty"),
                )
                self.fields["write_policy"].initial = "always"
                self.fields["column_mappings"].widget = forms.HiddenInput()
                self.initial["column_mappings"] = None
                self.fields["column_mappings"].disabled = True
                if mode == "value":
                    self.fields["target_column"].widget = forms.HiddenInput()
                    self.initial["target_column"] = None
                    self.fields["target_column"].disabled = True
            if self.initial.get("fetch") not in dict(self.fields["fetch"].choices):
                self.initial["fetch"] = "all" if mode == "populate" else "first"
            if self.initial.get("write_policy") not in dict(
                self.fields["write_policy"].choices
            ):
                self.initial["write_policy"] = (
                    "if_empty" if mode == "populate" else "always"
                )
            content_type = _content_type_from_initial(self.initial.get("model"))
            if content_type is None or content_type.model_class() is None:
                return
            source_model = content_type.model_class()
            self.fields["filters"].widget = FilterWidget(
                model=source_model, include_controls=False
            )
            source = _source_fields(source_model)
            self.fields["order_by"].queryset = source
            if mode == "value":
                self.fields["column"].queryset = compatible_columns(source, target)
            elif mode == "per_row":
                target_name = self.initial.get("target_column")
                destination = target_columns.filter(
                    field=str(target_name or "")
                ).first()
                self.fields["column"].queryset = compatible_columns(source, destination)
            else:
                self.fields["column"].queryset = source

        def clean(self) -> dict[str, Any]:
            """Validate selection shape, mappings, and draft placeholder dependencies."""
            cleaned = super().clean()
            mode = (cleaned.get("mode") or "populate") if is_collection else "value"
            cleaned["mode"] = mode
            content_type = cleaned.get("model")
            if content_type is None or content_type.model_class() is None:
                return cleaned
            source_model = content_type.model_class()
            fetch = cleaned.get("fetch")
            if not cleaned.get("write_policy"):
                cleaned["write_policy"] = "if_empty" if mode == "populate" else "always"
            if mode == "populate":
                if fetch != "all":
                    self.add_error(
                        "fetch",
                        "Populating a collection requires all matching records.",
                    )
                mappings = cleaned.get("column_mappings")
                if not isinstance(mappings, dict) or not mappings:
                    self.add_error(
                        "column_mappings", "Provide target-to-source column mappings."
                    )
                else:
                    resolved: dict[str, BehaviorFieldReference] = {}
                    source = _source_fields(source_model)
                    for target_name, source_name in mappings.items():
                        destination = (
                            target_columns.filter(field=target_name).first()
                            if isinstance(target_name, str)
                            else None
                        )
                        source_field = (
                            source.filter(field=source_name).first()
                            if isinstance(source_name, str)
                            else None
                        )
                        if (
                            destination is None
                            or source_field is None
                            or not compatible_columns(
                                source.filter(pk=source_field.pk), destination
                            ).exists()
                        ):
                            self.add_error(
                                "column_mappings",
                                f"Invalid or incompatible mapping: {target_name} → {source_name}.",
                            )
                            break
                        resolved[target_name] = BehaviorFieldReference(
                            field=source_field, draft=False
                        )
                    else:
                        cleaned["source_columns"] = resolved
            else:
                column = cleaned.get("column")
                destination = (
                    cleaned.get("target_column") if mode == "per_row" else target
                )
                if mode == "per_row" and destination is None:
                    self.add_error("target_column", "Select a target column.")
                if column is None:
                    self.add_error("column", "Select a source column.")
                elif (
                    destination is not None
                    and not compatible_columns(
                        _source_fields(source_model).filter(pk=column.pk), destination
                    ).exists()
                ):
                    self.add_error(
                        "column", "Source and target columns are incompatible."
                    )
                else:
                    cleaned["source_column"] = BehaviorFieldReference(
                        field=column, draft=False
                    )
                cleaned.pop("column", None)
                if mode == "per_row" and destination is not None:
                    cleaned["target_column"] = BehaviorFieldReference(
                        field=destination, permission="change", draft=False
                    )
            order_by = cleaned.get("order_by")
            if order_by is not None:
                cleaned["order_by"] = BehaviorFieldReference(
                    field=order_by, draft=False
                )
            try:
                filters = parse_filters(cleaned.get("filters"))
                if mode != "per_row" and any(
                    scope == "row" for scope, _ in filter_value_references(filters)
                ):
                    raise forms.ValidationError(
                        "Row placeholders require per-row mode."
                    )
                cleaned["filters"] = filters
                cleaned["value_references"] = resolve_behavior_field_references(
                    filters,
                    object_model=target.get_model(),
                    row_model=target.get_related_model() if mode == "per_row" else None,
                    allowed_row_fields=target_columns if mode == "per_row" else None,
                )
            except forms.ValidationError as error:
                self.add_error("filters", error)
            return cleaned

    return FetchForm


def fetch_targets(
    fields: QuerySet[ApplicationField],
    listener: ApplicationField | None,
) -> QuerySet[ApplicationField]:
    """Allow single values and one-to-many collections, excluding many-to-many."""
    return fields.exclude(field_type=FIELD_TYPE_REGISTRY.MANY_TO_MANY_FIELD.id)


def fetch(
    context: BehaviorContext, config: CleanedConfigData, user: BehaviorUser
) -> BehaviorResult:
    """Run one authorized lookup and return an atomic draft target update."""
    mode = config.get("mode") or "value"
    policy: str = config["write_policy"]
    current_rows = collection_rows(context.target_value) if mode != "value" else []
    if mode == "value" and not should_write_value(context.target_value, policy):
        return BehaviorResult()
    if mode == "populate":
        active = [row for row in current_rows if row.get("DELETE") not in DELETED]
        if policy == "if_empty" and active:
            return BehaviorResult()
        if policy == "replace_unsaved" and any(
            row.get("id") not in (None, "") for row in current_rows
        ):
            return BehaviorResult()
    if mode == "per_row" and not current_rows:
        return BehaviorResult()
    fields = (
        tuple(reference.field for reference in config["source_columns"].values())
        if mode == "populate"
        else (config["source_column"].field,)
    )
    order_reference: BehaviorFieldReference | None = config.get("order_by")
    order_by = order_reference.field if order_reference is not None else None
    changed = False
    if mode == "per_row":
        destination_reference: BehaviorFieldReference = config["target_column"]
        destination = destination_reference.field
        for row in current_rows:
            if row.get("DELETE") in DELETED or not should_write_value(
                row.get(destination.field), policy, field=destination
            ):
                continue
            filters = resolve_filter_values(
                config["filters"], object_values=context.values, row_values=row
            )
            result = _ordered_records(
                content_type=config["model"],
                source_fields=fields,
                filters=filters,
                fetch=config["fetch"],
                order_by=order_by,
                user=user,
            )
            if isinstance(result, BehaviorResult):
                return result
            if result:
                value = _record_value(result[0], fields[0])
                if row.get(destination.field) != value:
                    row[destination.field] = value
                    changed = True
        return (
            BehaviorResult(
                values=(
                    FieldValueUpdate(field=context.target_field, value=current_rows),
                )
            )
            if changed
            else BehaviorResult()
        )
    filters = resolve_filter_values(config["filters"], object_values=context.values)
    result = _ordered_records(
        content_type=config["model"],
        source_fields=fields,
        filters=filters,
        fetch=config["fetch"],
        order_by=order_by,
        user=user,
    )
    if isinstance(result, BehaviorResult) or not result:
        return result if isinstance(result, BehaviorResult) else BehaviorResult()
    if mode == "populate":
        new_rows = [
            {
                target_name: _record_value(record, reference.field)
                for target_name, reference in config["source_columns"].items()
            }
            for record in result
        ]
        rows = (
            [row for row in current_rows if row.get("DELETE") in DELETED] + new_rows
            if policy == "if_empty"
            else new_rows
        )
        if len(rows) > MAX_FETCH_ROWS:
            raise forms.ValidationError("The result would exceed 1000 collection rows.")
        return BehaviorResult(
            values=(FieldValueUpdate(field=context.target_field, value=rows),)
        )
    value = _record_value(result[0], fields[0])
    return (
        BehaviorResult()
        if context.target_value == value
        else BehaviorResult(
            values=(FieldValueUpdate(field=context.target_field, value=value),)
        )
    )


FETCH = BehaviorActionDefinition(
    id="fetch",
    label="Fetch",
    description="Find accessible records with filters and copy one value or populate collection rows.",
    requires_target_field=True,
    config_form_factory=fetch_config_form_factory,
    get_target_fields=fetch_targets,
    execute=fetch,
    group="Data lookup",
)
