from bloomerp.field_types.utils.form_field_factories import form
from django import forms
from bloomerp.field_types.display_options import LABEL_OPTION
from bloomerp.lookups import builtins as lookups
from bloomerp.field_types.construction import (
    BLANK_FIELD_OPTION,
    COMMON_FIELD_OPTIONS,
    DEFAULT_FIELD_OPTION,
    HELP_TEXT_FIELD_OPTION,
    NULL_FIELD_OPTION,
    PROPERTY_EXPRESSION,
    UPLOAD_TO_FIELD_OPTION,
)
from bloomerp.field_types.utils.widget_factories import widget
from bloomerp.model_fields.file_field import BloomerpFileField
from bloomerp.model_fields.status_field import StatusField
from bloomerp.widgets.code_editor_widget import CodeEditorWidget
from django.db import models
from bloomerp.field_types.registry import (
    FieldConstruction,
    FieldTypeDefinition,
    FieldTypeRegistry,
)
from bloomerp.field_types.builtins.display import BEHAVIORS_DISPLAY_OPTION
from bloomerp.field_types.lookups import TEXT_LOOKUPS

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
    render_value=lambda field, obj: f"<a class='text-primary' href='{(getattr(getattr(obj, field.field), 'url') if getattr(obj, field.field) else None)}'>{getattr(obj, field.field)}</a>",
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
    widget_factory=widget(CodeEditorWidget, attrs={}, **{"language": "json"}),
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

BLOOMERP_FILE_FIELD = FieldTypeDefinition(
    id="BloomerpFileField",
    icon="fa-solid fa-file-lines",
    label="Bloomerp File Field",
    model_field_cls=BloomerpFileField,
    lookups=(),
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
