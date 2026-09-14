from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Type

from django import forms
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db import transaction
from django.db.models import Model, QuerySet
from django.utils.datastructures import MultiValueDict
from django.db import models

from bloomerp.form_fields.one_to_many_field import (
    OneToManyCleanedData,
    OneToManyField,
)
from bloomerp.form_fields.structured_value import StructuredFormValue, serialize_form_value
from bloomerp.models import ApplicationField


AUTO_MANAGED_MODEL_FORM_FIELD_NAMES = frozenset(
    {
        "id",
        "pk",
        "datetime_created",
        "datetime_updated",
        "created_by",
        "updated_by",
        "comments",
        "files",
    }
)

# These fields belong in CRUD layouts, but their values are maintained by the
# model/application lifecycle rather than ordinary form submissions. Files are
# intentionally excluded: their structured form field owns its persistence.
READ_ONLY_AUTO_MANAGED_MODEL_FORM_FIELD_NAMES = (
    AUTO_MANAGED_MODEL_FORM_FIELD_NAMES - {"files"}
)


@dataclass(frozen=True, slots=True)
class CleanedO2MData:
    """One cleaned inline object and the operation requested for it."""

    object: Model
    created: bool = False
    changed: bool = False
    deleted: bool = False


def get_model_form_application_fields(
    model_cls: Type[Model],
    application_fields=None,
    *,
    exclude_auto_managed: bool = False,
) -> QuerySet[ApplicationField]:
    """Return ApplicationFields the BloomERP model-form factory can represent."""
    if application_fields is None:
        fields = ApplicationField.get_for_model(model_cls)
    elif isinstance(application_fields, QuerySet):
        fields = application_fields
    else:
        fields = ApplicationField.get_for_model(model_cls).filter(
            pk__in=[field.pk for field in application_fields],
        )

    if not exclude_auto_managed:
        return fields.order_by("field")

    # Use the same lifecycle policy as form construction. Files remain available
    # because their registered form factory owns editing and persistence.
    return fields.exclude(
        field__in=READ_ONLY_AUTO_MANAGED_MODEL_FORM_FIELD_NAMES,
    ).order_by("field")


class BloomerpModelForm(forms.ModelForm):
    """Model form that owns BloomERP field persistence and serialization."""

    bloomerp_non_model_field_names: frozenset[str] = frozenset()
    bloomerp_read_only_field_names: frozenset[str] = frozenset()

    def __init__(self, *args, **kwargs):
        self._structured_values_saved = False
        self._deserialized_data: dict[str, Any] | None = None
        super().__init__(*args, **kwargs)

    @classmethod
    def prepare_initial_data(
        cls,
        initial: dict[str, Any],
        data,
        application_fields,
    ) -> dict[str, Any]:
        """Convert flat or structured request values into form initial data."""
        prepared = initial.copy()
        for application_field in application_fields:
            field_name = application_field.field
            if field_name in data:
                prepared[field_name] = data.get(field_name)

            prefix = f"{field_name}__"
            if not any(key.startswith(prefix) for key in data):
                continue
            value = application_field.get_widget().value_from_datadict(
                data,
                {},
                field_name,
            )
            if value not in (None, "", []):
                prepared[field_name] = value
        return prepared

    @classmethod
    def prepare_bound_data(cls, data, files, instance, *, partial: bool = False):
        """Fill omitted fields from the instance for a partial model-form update."""
        if not partial or instance is None:
            return data

        prepared = data.copy()
        for field_name, form_field in cls.base_fields.items():
            has_structured_value = any(
                key.startswith(f"{field_name}__")
                for key in prepared
            )
            if has_structured_value or not form_field.widget.value_omitted_from_data(
                prepared,
                files,
                field_name,
            ):
                continue

            current_value = getattr(instance, field_name, None)
            if current_value in (None, ""):
                continue
            if hasattr(current_value, "all"):
                prepared.setlist(
                    field_name,
                    [str(obj.pk) for obj in current_value.all()],
                )
                continue

            prepared_value = form_field.prepare_value(current_value)
            if isinstance(prepared_value, (list, tuple, set)):
                prepared.setlist(
                    field_name,
                    [str(value) for value in prepared_value],
                )
            else:
                prepared[field_name] = prepared_value
        return prepared

    def changed_application_fields(self) -> QuerySet[ApplicationField]:
        return ApplicationField.get_for_model(self._meta.model).filter(
            field__in=self.changed_data,
        )

    def serialize_cleaned_data(self) -> dict[str, Any]:
        if not hasattr(self, "cleaned_data"):
            raise ValueError("The form must be cleaned before its data can be serialized.")
        return {
            field_name: serialize_form_value(value)
            for field_name, value in self.cleaned_data.items()
        }

    def deserialize_cleaned_data(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert JSON-compatible field values back into cleaned Python values."""
        return {
            field_name: self.fields[field_name].clean(value)
            for field_name, value in data.items()
            if field_name in self.fields
        }

    def _clean_fields(self) -> None:
        if self._deserialized_data is None:
            super()._clean_fields()
            return

        for field_name, field in self.fields.items():
            try:
                if field.disabled:
                    value = self[field_name].initial
                else:
                    value = self._deserialized_data.get(field_name)
                self.cleaned_data[field_name] = field.clean(value)

                field_clean_method = getattr(self, f"clean_{field_name}", None)
                if field_clean_method is not None:
                    self.cleaned_data[field_name] = field_clean_method()
            except ValidationError as error:
                self.add_error(field_name, error)

    def _save_model_fields(self, *, commit: bool) -> Model:
        detached_values = {
            field_name: self.cleaned_data.pop(field_name)
            for field_name in self.bloomerp_non_model_field_names
            if field_name in self.cleaned_data
        }
        try:
            return super().save(commit=commit)
        finally:
            self.cleaned_data.update(detached_values)

    def save_structured_fields(self) -> None:
        if self._structured_values_saved:
            return
        if self.instance.pk is None:
            raise ValueError("The parent object must be saved before its structured fields.")

        for value in self.cleaned_data.values():
            if isinstance(value, StructuredFormValue):
                value.save(self.instance)
        self._structured_values_saved = True

    def save_o2m(self) -> None:
        """Backward-compatible alias for callers migrating to ``save()``."""
        self.save_structured_fields()

    def save(self, commit: bool = True) -> Model:
        if not commit:
            return self._save_model_fields(commit=False)

        with transaction.atomic():
            self.instance = self._save_model_fields(commit=True)
            self.save_structured_fields()
        return self.instance

    def get_cleaned_o2m_data(self) -> dict[str, list[CleanedO2MData]]:
        """Return cleaned inline objects grouped by their parent form field."""
        if not hasattr(self, "cleaned_data"):
            raise ValueError("The form must be cleaned before accessing o2m data.")

        o2m_data: dict[str, list[CleanedO2MData]] = {}
        for field_name, value in self.cleaned_data.items():
            if not isinstance(value, OneToManyCleanedData):
                continue

            entries = [
                CleanedO2MData(
                    object=instance,
                    created=instance._state.adding,
                    changed=(
                        not instance._state.adding
                        and child_form.has_changed()
                    ),
                )
                for child_form, instance in zip(value._forms, value.to_save)
            ]
            entries.extend(
                CleanedO2MData(object=instance, deleted=True)
                for instance in value.to_delete
            )
            o2m_data[field_name] = entries

        return o2m_data

    @classmethod
    def from_deserialized_data(
        cls,
        data: dict[str, Any],
        **form_kwargs: Any,
    ) -> "BloomerpModelForm":
        """Return a bound form that validates previously serialized cleaned data."""
        bound_data = MultiValueDict()
        for field_name, value in data.items():
            field = cls.base_fields.get(field_name)
            if isinstance(field, OneToManyField) and isinstance(value, list):
                for row_index, row in enumerate(value):
                    if not isinstance(row, dict):
                        continue
                    for row_field_name, row_value in row.items():
                        key = f"{field_name}__{row_index}__{row_field_name}"
                        if isinstance(row_value, list):
                            bound_data.setlist(key, row_value)
                        else:
                            bound_data[key] = row_value
            elif isinstance(value, list):
                bound_data.setlist(field_name, value)
            else:
                bound_data[field_name] = value

        form = cls(data=bound_data, **form_kwargs)
        form._deserialized_data = data
        return form


def _django_saves_field(model_field) -> bool:
    """Whether an editable Django field belongs in ModelForm.Meta.fields."""
    return bool(
        model_field is not None
        and model_field.editable
        and (model_field.concrete or model_field.many_to_many)
    )


def _build_registered_form_field(application_field: ApplicationField) -> forms.Field:
    """Render display-only fields when neither Django nor a factory supplies a form."""
    from bloomerp.field_types.utils.form_field_factories import (
        build_form_field,
        build_widget,
    )

    form_field = build_form_field(application_field)
    if form_field is not None:
        return form_field

    return forms.Field(
        required=False,
        label=application_field.title,
        widget=build_widget(application_field),
        disabled=True,
    )


def bloomerp_modelform_factory(
    model_cls: Type[Model],
    fields: list[str] | str = "__all__",
) -> Type[BloomerpModelForm]:
    """Create a form in which every requested ApplicationField is represented."""
    application_fields = ApplicationField.get_for_model(model_cls)
    if fields != "__all__":
        application_fields = application_fields.filter(field__in=fields)
    application_fields = list(application_fields)

    model_field_names: list[str] = []
    declared_form_fields: dict[str, forms.Field] = {}
    non_model_field_names: set[str] = set()
    read_only_field_names: set[str] = set()

    for application_field in application_fields:
        field_name = application_field.field
        try:
            model_field = application_field._get_model_field()
        except FieldDoesNotExist:
            model_field = None

        managed_by_application = (
            field_name in READ_ONLY_AUTO_MANAGED_MODEL_FORM_FIELD_NAMES
        )
        form_field = _build_registered_form_field(application_field)

        # Lifecycle-managed values remain visible, but ignore submitted changes.
        if managed_by_application or form_field.disabled:
            form_field.disabled = True
            read_only_field_names.add(field_name)

        # Meta.fields identifies values Django saves. Reverse relations and
        # virtual fields instead use BloomERP's structured-value persistence.
        if not managed_by_application and _django_saves_field(model_field):
            model_field_names.append(field_name)
        else:
            non_model_field_names.add(field_name)
        declared_form_fields[field_name] = form_field

    meta_class = type("Meta", (), {"model": model_cls, "fields": model_field_names})

    def __init__(self, *args, **kwargs):
        BloomerpModelForm.__init__(self, *args, **kwargs)
        instance = getattr(self, "instance", None)

        for field_name in self.bloomerp_read_only_field_names:
            self.fields[field_name].disabled = True
        for form_field in self.fields.values():
            if isinstance(form_field, OneToManyField):
                form_field.bind_parent(instance)

        if instance is None or instance._state.adding:
            return
        for field_name in self.bloomerp_non_model_field_names:
            value = getattr(instance, field_name, None) or getattr(
                instance, f"{field_name}_set", None
            )
            if hasattr(value, "all"):
                value = list(value.all())
            self.initial[field_name] = value

    attrs = dict(declared_form_fields)
    attrs["__init__"] = __init__
    attrs["Meta"] = meta_class
    attrs["bloomerp_non_model_field_names"] = frozenset(non_model_field_names)
    attrs["bloomerp_read_only_field_names"] = frozenset(read_only_field_names)
    return type(f"{model_cls._meta.model_name}Form", (BloomerpModelForm,), attrs)
