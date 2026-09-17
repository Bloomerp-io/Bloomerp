from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from django import forms
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db.models import ManyToManyField, Model, OneToOneField
from django.db.models.fields.reverse_related import (
    ManyToManyRel,
    ManyToOneRel,
    OneToOneRel,
)
from django.utils.text import capfirst
from django.utils.translation import gettext_lazy as _
from pydantic import Field

from bloomerp.dataviews.definition import BaseDataview, DataviewState
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager

if TYPE_CHECKING:
    from bloomerp.models.files.file_folder import FileFolder


def _is_file_model(model: type[Model] | None) -> bool:
    """Identify the File model without importing it back into its own config."""
    return bool(
        model is not None
        and model._meta.app_label == "bloomerp"
        and model._meta.model_name == "file"
    )


def _resolve_content_type(state: DataviewState) -> ContentType | None:
    """Resolve the model whose related files are being configured."""
    state_model = getattr(state, "model", None)
    if state_model is not None and not _is_file_model(state_model):
        return getattr(state, "content_type", None) or ContentType.objects.get_for_model(
            state_model
        )

    for group in state.filters or []:
        for condition in group.conditions:
            if condition.field_path not in {"content_type", "content_type_id"}:
                continue
            if condition.lookup_id != "equals":
                continue
            try:
                content_type_id = int(condition.value)
            except (TypeError, ValueError):
                return None
            return ContentType.objects.filter(pk=content_type_id).first()
    return None

def _resolve_object(state: DataviewState) -> Model | None:
    """Resolve the host object encoded by the File filters."""
    content_type = _resolve_content_type(state)
    model = content_type.model_class() if content_type is not None else None
    if model is None:
        return None

    object_id = None
    for group in state.filters or []:
        for condition in group.conditions:
            if condition.field_path != "object_id":
                continue
            if condition.lookup_id != "equals":
                continue
            object_id = condition.value
            break
        if object_id is not None:
            break

    if object_id is None or object_id == "":
        return None

    try:
        return model._base_manager.filter(pk=object_id).first()
    except (TypeError, ValueError, OverflowError, ValidationError):
        return None

def _resolve_folder(state: DataviewState) -> FileFolder | None:
    """Resolve the current folder from the File Browser query parameters."""
    folder_id = state.request.GET.get("folder_id")
    if not folder_id:
        return None

    from bloomerp.models.files.file_folder import FileFolder

    try:
        folder = FileFolder.objects.filter(pk=folder_id).first()
    except (TypeError, ValueError, OverflowError, ValidationError):
        return None
    return folder



def _get_related_fields(model: type[Model]) -> list[str]:
    """Return object-bearing relations reachable from the host model."""
    supported_relation_types = (
        ManyToOneRel,
        OneToOneField,
        OneToOneRel,
        ManyToManyField,
        ManyToManyRel,
    )
    return [
        field.name
        for field in model._meta.get_fields()
        if field.name
        and isinstance(field, supported_relation_types)
        and field.related_model is not None
        and not getattr(field, "hidden", False)
        and not field.related_model._meta.auto_created
    ]


class RelatedFieldsChoiceField(forms.MultipleChoiceField):
    """Expose one host's relations while cleaning to the persisted mapping."""

    def __init__(
        self,
        *,
        content_type_id: int,
        existing: dict[int, list[str]],
        **kwargs,
    ):
        self.content_type_id = content_type_id
        self.existing = {
            int(key): list(value)
            for key, value in existing.items()
        }
        super().__init__(**kwargs)

    def clean(self, value):
        selected_fields = super().clean(value)
        related_fields = dict(self.existing)
        related_fields[self.content_type_id] = selected_fields
        return related_fields


class PreservedRelatedFieldsField(forms.Field):
    """Keep the mapping unchanged when no host content type is in scope."""

    widget = forms.HiddenInput

    def __init__(self, *, existing: dict[int, list[str]], **kwargs):
        self.existing = {
            int(key): list(value)
            for key, value in existing.items()
        }
        super().__init__(required=False, **kwargs)

    def clean(self, _value):
        return dict(self.existing)


class FileBrowserDataview(BaseDataview):
    view_type: Literal["file_browser"] = "file_browser"
    split_view_enabled: bool = True
    related_fields: dict[int, list[str]] = Field(default_factory=dict)

    @classmethod
    def form_factory(cls, state: DataviewState) -> type[forms.Form]:
        existing = getattr(state.options, "related_fields", {}) or {}
        host_content_type = _resolve_content_type(state)
        host_model = (
            host_content_type.model_class()
            if host_content_type is not None
            else None
        )
        if host_content_type is None or host_model is None:
            return type(
                "FileBrowserDataviewOptionsForm",
                (forms.Form,),
                {"related_fields": PreservedRelatedFieldsField(existing=existing)},
            )

        permission_manager = UserPolicyManager(state.request.user)
        if not permission_manager.has_global_permission(
            host_model,
            BloomerpPermission.VIEW,
        ):
            return type(
                "FileBrowserDataviewOptionsForm",
                (forms.Form,),
                {"related_fields": PreservedRelatedFieldsField(existing=existing)},
            )

        choices = []
        for field_name in _get_related_fields(host_model):
            model_field = host_model._meta.get_field(field_name)
            related_model = model_field.related_model
            if not permission_manager.has_global_permission(
                related_model,
                BloomerpPermission.VIEW,
            ):
                continue
            field_label = getattr(model_field, "verbose_name", None) or field_name
            choices.append((
                field_name,
                _("%(field)s (%(model)s)") % {
                    "field": capfirst(str(field_label)),
                    "model": capfirst(str(related_model._meta.verbose_name)),
                },
            ))

        content_type_id = host_content_type.pk
        related_fields_field = RelatedFieldsChoiceField(
            content_type_id=content_type_id,
            existing=existing,
            choices=choices,
            required=False,
            label=_("Related objects"),
            help_text=_("Include files attached to objects through these relations."),
        )
        related_fields_field.widget.attrs.setdefault(
            "class",
            "select select-sm w-40 bg-base border-0",
        )

        class FileBrowserDataviewOptionsForm(forms.Form):
            related_fields = related_fields_field

            def __init__(self, *args, **kwargs):
                initial = dict(kwargs.get("initial") or {})
                configured = initial.get("related_fields", existing) or {}
                initial["related_fields"] = configured.get(
                    content_type_id,
                    configured.get(str(content_type_id), []),
                )
                kwargs["initial"] = initial
                super().__init__(*args, **kwargs)

        return FileBrowserDataviewOptionsForm
