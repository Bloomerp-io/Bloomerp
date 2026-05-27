from importlib import import_module
from typing import Any

__all__ = [
    "Lookup",
    "LookupDefinition",
    "TEXT_LOOKUPS",
    "NUMERIC_LOOKUPS",
    "DATE_LOOKUPS",
    "BOOLEAN_LOOKUPS",
    "FieldOption",
    "NULL_FIELD_OPTION",
    "BLANK_FIELD_OPTION",
    "UNIQUE_FIELD_OPTION",
    "DB_INDEX_FIELD_OPTION",
    "DEFAULT_FIELD_OPTION",
    "HELP_TEXT_FIELD_OPTION",
    "MAX_LENGTH_FIELD_OPTION",
    "MAX_DIGITS_FIELD_OPTION",
    "DECIMAL_PLACES_FIELD_OPTION",
    "UPLOAD_TO_FIELD_OPTION",
    "AUTO_NOW_FIELD_OPTION",
    "AUTO_NOW_ADD_FIELD_OPTION",
    "RELATED_NAME_FIELD_OPTION",
    "VERBOSE_NAME_FIELD_OPTION",
    "TO_FIELD_OPTION",
    "ON_DELETE_FIELD_OPTION",
    "CHOICES_FIELD_OPTION",
    "COMMON_FIELD_OPTIONS",
    "COMMON_TEXT_FIELD_OPTIONS",
    "COMMON_CHOICE_FIELD_OPTIONS",
    "COMMON_RELATION_FIELD_OPTIONS",
    "FieldDisplayOption",
    "FieldTypeDefinition",
    "FieldType",
]

_ATTR_TO_MODULE = {
    "Lookup": ".lookups",
    "LookupDefinition": ".lookups",
    "TEXT_LOOKUPS": ".lookups",
    "NUMERIC_LOOKUPS": ".lookups",
    "DATE_LOOKUPS": ".lookups",
    "BOOLEAN_LOOKUPS": ".lookups",
    "FieldOption": ".options",
    "NULL_FIELD_OPTION": ".options",
    "BLANK_FIELD_OPTION": ".options",
    "UNIQUE_FIELD_OPTION": ".options",
    "DB_INDEX_FIELD_OPTION": ".options",
    "DEFAULT_FIELD_OPTION": ".options",
    "HELP_TEXT_FIELD_OPTION": ".options",
    "MAX_LENGTH_FIELD_OPTION": ".options",
    "MAX_DIGITS_FIELD_OPTION": ".options",
    "DECIMAL_PLACES_FIELD_OPTION": ".options",
    "UPLOAD_TO_FIELD_OPTION": ".options",
    "AUTO_NOW_FIELD_OPTION": ".options",
    "AUTO_NOW_ADD_FIELD_OPTION": ".options",
    "RELATED_NAME_FIELD_OPTION": ".options",
    "VERBOSE_NAME_FIELD_OPTION": ".options",
    "TO_FIELD_OPTION": ".options",
    "ON_DELETE_FIELD_OPTION": ".options",
    "CHOICES_FIELD_OPTION": ".options",
    "COMMON_FIELD_OPTIONS": ".options",
    "COMMON_TEXT_FIELD_OPTIONS": ".options",
    "COMMON_CHOICE_FIELD_OPTIONS": ".options",
    "COMMON_RELATION_FIELD_OPTIONS": ".options",
    "FieldDisplayOption": ".display_options",
    "FieldTypeDefinition": ".types",
    "FieldType": ".types",
}


def __getattr__(name: str) -> Any:
    module_name = _ATTR_TO_MODULE.get(name)
    if not module_name:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
