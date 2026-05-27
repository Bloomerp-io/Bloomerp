from dataclasses import dataclass, field as dataclass_field
from typing import Any, Callable, Literal

from django.db import models
from typing import Optional
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bloomerp.models import ApplicationField

@dataclass
class FieldOption:
    id: str
    label: str
    primitive_input_type: Literal['text', 'number', 'bool', 'list', 'model', 'choices', 'callable']
    description: Optional[str] = None
    required: bool = False
    default_value: Any = None
    choices: list[str] | None = None  # valid values when primitive_input_type='choices'
    mutually_exclusive_with: list[str] = dataclass_field(default_factory=list)
    python_type: Any = Any

    def __hash__(self) -> int:
        return hash(self.id)


NULL_FIELD_OPTION = FieldOption(
    id="null",
    label="Nullable",
    primitive_input_type="bool",
    description="Whether this field can be set to null",
    default_value=True,
    python_type=bool,
)
BLANK_FIELD_OPTION = FieldOption(
    id="blank",
    label="Allow Empty Input",
    primitive_input_type="bool",
    description="Whether this field can be left empty in forms.",
    default_value=True,
    python_type=bool,
)
UNIQUE_FIELD_OPTION = FieldOption(
    id="unique",
    label="Unique",
    primitive_input_type="bool",
    description="Whether values for this field must be unique.",
    default_value=False,
    python_type=bool,
)
DB_INDEX_FIELD_OPTION = FieldOption(
    id="db_index",
    label="Indexed",
    primitive_input_type="bool",
    description="Whether to create a database index for this field.",
    default_value=False,
    python_type=bool,
)
DEFAULT_FIELD_OPTION = FieldOption(
    id="default",
    label="Default Value",
    primitive_input_type="text",
    description="Default value used when no value is provided.",
    python_type=Any,
)
HELP_TEXT_FIELD_OPTION = FieldOption(
    id="help_text",
    label="Help Text",
    primitive_input_type="text",
    description="Optional helper text shown to end users on forms.",
    default_value="",
    python_type=str,
)
MAX_LENGTH_FIELD_OPTION = FieldOption(
    id="max_length",
    label="Maximum Length",
    primitive_input_type="number",
    description="Maximum number of characters allowed.",
    required=True,
    python_type=int,
)
MAX_DIGITS_FIELD_OPTION = FieldOption(
    id="max_digits",
    label="Max Digits",
    primitive_input_type="number",
    description="Maximum number of digits stored by this decimal field.",
    required=True,
    python_type=int,
)
DECIMAL_PLACES_FIELD_OPTION = FieldOption(
    id="decimal_places",
    label="Decimal Places",
    primitive_input_type="number",
    description="Number of decimal places stored by this decimal field.",
    required=True,
    python_type=int,
)
UPLOAD_TO_FIELD_OPTION = FieldOption(
    id="upload_to",
    label="Upload Folder",
    primitive_input_type="text",
    description="Storage path prefix used when uploading files.",
    default_value="",
    python_type=str,
)
AUTO_NOW_FIELD_OPTION = FieldOption(
    id="auto_now",
    label="Auto Update On Save",
    primitive_input_type="bool",
    description="Automatically update this field to the current date/time on each save.",
    default_value=False,
    mutually_exclusive_with=["auto_now_add"],
    python_type=bool,
)
AUTO_NOW_ADD_FIELD_OPTION = FieldOption(
    id="auto_now_add",
    label="Auto Set On Create",
    primitive_input_type="bool",
    description="Automatically set this field to the current date/time when the object is created.",
    default_value=False,
    mutually_exclusive_with=["auto_now"],
    python_type=bool,
)
RELATED_NAME_FIELD_OPTION = FieldOption(
    id="related_name",
    label="Reverse Relation Name",
    primitive_input_type="text",
    description="Optional related_name used on the reverse side of relationships.",
    python_type=str,
)
VERBOSE_NAME_FIELD_OPTION = FieldOption(
    id="verbose_name",
    label="Label",
    primitive_input_type="text",
    description="Human-readable name shown as the field label in forms and admin.",
    python_type=str,
)
TO_FIELD_OPTION = FieldOption(
    id="to",
    label="Related Model",
    primitive_input_type="model",
    description="The model this field points to.",
    required=True,
    python_type=type[models.Model] | str,
)
ON_DELETE_FIELD_OPTION = FieldOption(
    id="on_delete",
    label="On Delete Behaviour",
    primitive_input_type="choices",
    description="What happens to this object when the related object is deleted.",
    required=True,
    default_value="CASCADE",
    choices=["CASCADE", "PROTECT", "SET_NULL", "SET_DEFAULT", "DO_NOTHING"],
    python_type=Callable[..., Any],
)
CHOICES_FIELD_OPTION = FieldOption(
    id="choices",
    label="Choices",
    primitive_input_type="choices",
    description="Fixed options available for this field.",
    required=True,
    default_value=[],
    python_type=list[tuple[Any, Any]],
)
COMMON_FIELD_OPTIONS = [
    VERBOSE_NAME_FIELD_OPTION,
    NULL_FIELD_OPTION,
    BLANK_FIELD_OPTION,
    UNIQUE_FIELD_OPTION,
    DB_INDEX_FIELD_OPTION,
    DEFAULT_FIELD_OPTION,
    HELP_TEXT_FIELD_OPTION,
]
COMMON_TEXT_FIELD_OPTIONS = [
    *COMMON_FIELD_OPTIONS,
    MAX_LENGTH_FIELD_OPTION,
]
COMMON_CHOICE_FIELD_OPTIONS = [
    *COMMON_FIELD_OPTIONS,
    CHOICES_FIELD_OPTION,
    MAX_LENGTH_FIELD_OPTION,
]
COMMON_RELATION_FIELD_OPTIONS = [
    TO_FIELD_OPTION,
    VERBOSE_NAME_FIELD_OPTION,
    NULL_FIELD_OPTION,
    BLANK_FIELD_OPTION,
    DB_INDEX_FIELD_OPTION,
    RELATED_NAME_FIELD_OPTION,
    HELP_TEXT_FIELD_OPTION,
]