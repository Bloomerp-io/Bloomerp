from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django import forms
from django.db import models
from django.db.models import (
    CharField,
    Exists,
    Expression,
    Func,
    OuterRef,
    Q,
    UUIDField,
    Value,
)
from django.db.models.functions import Cast, Concat, Substr

from bloomerp.field_types.builtins.display import BEHAVIORS_DISPLAY_OPTION
from bloomerp.field_types.construction import (
    BLANK_FIELD_OPTION,
    COMMON_FIELD_OPTIONS,
    DEFAULT_FIELD_OPTION,
    HELP_TEXT_FIELD_OPTION,
    NULL_FIELD_OPTION,
    PROPERTY_EXPRESSION,
    UPLOAD_TO_FIELD_OPTION,
    FieldConstructionOption,
)
from bloomerp.field_types.display_options import LABEL_OPTION
from bloomerp.field_types.lookups import TEXT_LOOKUPS
from bloomerp.field_types.registry import (
    FieldConstruction,
    FieldTypeDefinition,
    FieldTypeRegistry,
)
from bloomerp.field_types.utils.file_values import (
    load_file_field_values,
    render_file_field_value,
)
from bloomerp.field_types.utils.form_field_factories import form
from bloomerp.field_types.utils.widget_factories import widget
from bloomerp.lookups import builtins as lookups
from bloomerp.lookups.builtins.utils import is_truthy
from bloomerp.lookups.definition import BoundLookup, CompiledLookup
from bloomerp.model_fields.file_field import BloomerpFileField
from bloomerp.model_fields.status_field import StatusField
from bloomerp.widgets.code_editor_widget import CodeEditorWidget

if TYPE_CHECKING:
    from django.db.backends.base.base import BaseDatabaseWrapper
    from django.db.models.sql.compiler import SQLCompiler

    from bloomerp.models import ApplicationField


PROPERTY = FieldTypeDefinition(
    id="Property",
    icon="fa-solid fa-sliders",
    label="Property",
    lookups=(),
    construction=FieldConstruction(defaults={}, options=(PROPERTY_EXPRESSION,)),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)

FILE_FIELD = FieldTypeDefinition(
    id="FileField",
    icon="fa-solid fa-file",
    model_field_cls=models.FileField,
    label="File Field",
    lookups=(),
    construction=FieldConstruction(
        defaults={"upload_to": "uploads/"},
        options=(
            NULL_FIELD_OPTION,
            BLANK_FIELD_OPTION,
            UPLOAD_TO_FIELD_OPTION,
            HELP_TEXT_FIELD_OPTION,
        ),
    ),
    render_value=lambda field, obj: (
        f"<a class='text-primary' href='{(getattr(obj, field.field).url if getattr(obj, field.field) else None)}'>{getattr(obj, field.field)}</a>"
    ),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)

IMAGE_FIELD = FieldTypeDefinition(
    id="ImageField",
    icon="fa-solid fa-image",
    model_field_cls=models.ImageField,
    label="Image Field",
    lookups=(),
    construction=FieldConstruction(
        defaults={"upload_to": "images/"},
        options=(
            NULL_FIELD_OPTION,
            BLANK_FIELD_OPTION,
            UPLOAD_TO_FIELD_OPTION,
            HELP_TEXT_FIELD_OPTION,
        ),
    ),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)

UUID_FIELD = FieldTypeDefinition(
    id="UUIDField",
    icon="fa-solid fa-fingerprint",
    model_field_cls=models.UUIDField,
    label="UUID Field",
    lookups=(lookups.EQUALS, lookups.VALUES_IN, lookups.IS_NULL),
    construction=FieldConstruction(defaults={}, options=tuple(COMMON_FIELD_OPTIONS)),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)

BINARY_FIELD = FieldTypeDefinition(
    id="BinaryField",
    icon="fa-solid fa-code",
    model_field_cls=models.BinaryField,
    label="Binary Field",
    lookups=(),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)

JSON_FIELD = FieldTypeDefinition(
    form_factory=form(forms.JSONField),
    id="JSONField",
    icon="fa-solid fa-code",
    model_field_cls=models.JSONField,
    label="JSON Field",
    lookups=(
        lookups.CONTAINS,
        lookups.EQUALS,
        lookups.IS_NULL,
        lookups.JSON_KEY,
    ),
    construction=FieldConstruction(
        defaults={"default": dict},
        options=(
            NULL_FIELD_OPTION,
            BLANK_FIELD_OPTION,
            DEFAULT_FIELD_OPTION,
            HELP_TEXT_FIELD_OPTION,
        ),
    ),
    widget_factory=widget(CodeEditorWidget, attrs={}, language="json"),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)

ARRAY_FIELD = FieldTypeDefinition(
    id="ArrayField",
    icon="fa-solid fa-list-ol",
    label="Array Field",
    lookups=(lookups.CONTAINS, lookups.IS_NULL),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)

HSTORE_FIELD = FieldTypeDefinition(
    id="HStoreField",
    icon="fa-solid fa-box-archive",
    label="HStore Field",
    lookups=(),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)

STATUS_FIELD = FieldTypeDefinition(
    id="StatusField",
    icon="fa-solid fa-signal",
    label="Status Field",
    model_field_cls=StatusField,
    lookups=tuple(TEXT_LOOKUPS),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)


class CanonicalUUIDText(Func):
    """Match canonical reference IDs even when a backend stores UUIDs without hyphens."""

    output_field = CharField()

    def as_sql(
        self,
        compiler: SQLCompiler,
        connection: BaseDatabaseWrapper,
        **extra_context: Any,
    ) -> tuple[str, list[Any]]:
        """Convert the outer UUID to text without transforming the indexed reference column."""
        text = Cast(self.source_expressions[0], output_field=CharField())
        if not connection.features.has_native_uuid_field:
            text = Concat(
                Substr(text, 1, 8),
                Value("-"),
                Substr(text, 9, 4),
                Value("-"),
                Substr(text, 13, 4),
                Value("-"),
                Substr(text, 17, 4),
                Value("-"),
                Substr(text, 21, 12),
                output_field=CharField(),
            )
        sql, parameters = compiler.compile(text)
        return sql, list(parameters)


def file_field_is_null_q_factory(
    application_field: ApplicationField, field_path: str, expression: str, value: Any
) -> CompiledLookup:
    """Match empty or populated file fields using their scoped reference existence."""
    from bloomerp.models import FileFieldReference

    prefix, _separator, _name = field_path.rpartition("__")
    owner_path = f"{prefix}__pk" if prefix else "pk"
    owner_id: Expression = OuterRef(owner_path)
    if isinstance(application_field.get_model()._meta.pk, UUIDField):
        owner_id = CanonicalUUIDText(owner_id)
    else:
        owner_id = Cast(owner_id, output_field=CharField())
    references = FileFieldReference.objects.filter(
        application_field_id=application_field.pk,
        object_id=owner_id,
    )
    exists = Exists(references)
    return CompiledLookup(predicate=Q(~exists if is_truthy(value) else exists))



BLOOMERP_FILE_FIELD = FieldTypeDefinition(
    id="BloomerpFileField",
    icon="fa-solid fa-file-lines",
    label="Bloomerp File Field",
    model_field_cls=BloomerpFileField,
    batch_value_loader=load_file_field_values,
    render_value=render_file_field_value,
    lookups=(
        BoundLookup(
            lookup=lookups.IS_NULL,
            q_factory=file_field_is_null_q_factory,
            python_evaluator=lambda actual, expected: (not actual) is is_truthy(expected),
        ),
    ),
    construction=FieldConstruction(
        defaults={"blank": True, "multiple": False},
        options=(
            BLANK_FIELD_OPTION,
            HELP_TEXT_FIELD_OPTION,
            FieldConstructionOption(
                id="multiple",
                label="Allow Multiple Files",
                primitive_input_type="bool",
                default_value=False,
                python_type=bool,
            ),
            FieldConstructionOption(
                id="allowed_extensions",
                label="Allowed File Extensions",
                primitive_input_type="list",
                description="Optional extensions such as .pdf and .docx; empty accepts all files.",
                python_type=list[str],
            ),
            FieldConstructionOption(
                id="max_files",
                label="Maximum Files",
                primitive_input_type="number",
                python_type=int,
            ),
            FieldConstructionOption(
                id="max_file_size",
                label="Maximum File Size (Bytes)",
                primitive_input_type="number",
                python_type=int,
            ),
        ),
    ),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)


def register(registry: FieldTypeRegistry) -> None:
    registry.register("PROPERTY", PROPERTY)
    registry.register("FILE_FIELD", FILE_FIELD)
    registry.register("IMAGE_FIELD", IMAGE_FIELD)
    registry.register("UUID_FIELD", UUID_FIELD)
    registry.register("BINARY_FIELD", BINARY_FIELD)
    registry.register("JSON_FIELD", JSON_FIELD)
    registry.register("ARRAY_FIELD", ARRAY_FIELD)
    registry.register("HSTORE_FIELD", HSTORE_FIELD)
    registry.register("STATUS_FIELD", STATUS_FIELD)
    registry.register("BLOOMERP_FILE_FIELD", BLOOMERP_FILE_FIELD)
