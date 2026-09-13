from importlib import import_module
from typing import Any

__all__ = [
    "LookupDefinition",
    "TEXT_LOOKUPS",
    "NUMERIC_LOOKUPS",
    "DATE_LOOKUPS",
    "WEEK_LOOKUPS",
    "BOOLEAN_LOOKUPS",
    "FieldConstructionOption",
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
    "FIELD_TYPE_REGISTRY",
    "FieldContext",
    "FieldConstruction",
    "load_builtin_field_types",
]

_ATTR_TO_MODULE = {
    "LookupDefinition": "bloomerp.lookups.definition",
    "TEXT_LOOKUPS": ".lookups",
    "NUMERIC_LOOKUPS": ".lookups",
    "DATE_LOOKUPS": ".lookups",
    "WEEK_LOOKUPS": ".lookups",
    "BOOLEAN_LOOKUPS": ".lookups",
    "FieldConstructionOption": ".construction",
    "NULL_FIELD_OPTION": ".construction",
    "BLANK_FIELD_OPTION": ".construction",
    "UNIQUE_FIELD_OPTION": ".construction",
    "DB_INDEX_FIELD_OPTION": ".construction",
    "DEFAULT_FIELD_OPTION": ".construction",
    "HELP_TEXT_FIELD_OPTION": ".construction",
    "MAX_LENGTH_FIELD_OPTION": ".construction",
    "MAX_DIGITS_FIELD_OPTION": ".construction",
    "DECIMAL_PLACES_FIELD_OPTION": ".construction",
    "UPLOAD_TO_FIELD_OPTION": ".construction",
    "AUTO_NOW_FIELD_OPTION": ".construction",
    "AUTO_NOW_ADD_FIELD_OPTION": ".construction",
    "RELATED_NAME_FIELD_OPTION": ".construction",
    "VERBOSE_NAME_FIELD_OPTION": ".construction",
    "TO_FIELD_OPTION": ".construction",
    "ON_DELETE_FIELD_OPTION": ".construction",
    "CHOICES_FIELD_OPTION": ".construction",
    "COMMON_FIELD_OPTIONS": ".construction",
    "COMMON_TEXT_FIELD_OPTIONS": ".construction",
    "COMMON_CHOICE_FIELD_OPTIONS": ".construction",
    "COMMON_RELATION_FIELD_OPTIONS": ".construction",
    "FieldDisplayOption": ".display_options",
    "FieldTypeDefinition": ".registry",
    "FIELD_TYPE_REGISTRY": ".registry",
    "FieldContext": ".registry",
    "FieldConstruction": ".registry",
    "load_builtin_field_types": ".registry",
}


def __getattr__(name: str) -> Any:
    module_name = _ATTR_TO_MODULE.get(name)
    if not module_name:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name, __name__)
    value = module.load_builtin_field_types() if name == "FIELD_TYPE_REGISTRY" else getattr(module, name)
    globals()[name] = value
    return value
