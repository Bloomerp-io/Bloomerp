from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, PrivateAttr, model_validator

from bloomerp.filters.definition import Filter, FilterCondition


class PermissionMatch(Enum):
    """
    Enum representing the type of match for a permission.
    """
    ALL = "all"
    ANY = "any"


class PermissionScope(Enum):
    """
    Enum representing the scope of a permission.
    """
    GLOBAL = "global"
    FIELD = "field"
    ROW = "row"


@dataclass
class BloomerpPermissionDefinition:
    """
    A class to define a permission in the Bloomerp system.
    """
    name: str
    codename: str
    description: str
    scopes : list[PermissionScope] = None
    
    
class BloomerpPermission(Enum):
    """
    Enum representing the permissions in the Bloomerp system.
    Each permission is defined with a name, codename, description, and scopes.
    """
    ADD = BloomerpPermissionDefinition(
        name="Add",
        codename="add",
        description="Permission to add new records.",
        scopes=[PermissionScope.GLOBAL, PermissionScope.FIELD, PermissionScope.ROW]
    )
    CHANGE = BloomerpPermissionDefinition(
        name="Change",
        codename="change",
        description="Permission to change existing records.",
        scopes=[PermissionScope.GLOBAL, PermissionScope.FIELD, PermissionScope.ROW]
    )
    DELETE = BloomerpPermissionDefinition(
        name="Delete",
        codename="delete",
        description="Permission to delete records.",
        scopes=[PermissionScope.GLOBAL, PermissionScope.ROW]
    )
    VIEW = BloomerpPermissionDefinition(
        name="View",
        codename="view",
        description="Permission to view records.",
        scopes=[PermissionScope.GLOBAL, PermissionScope.FIELD, PermissionScope.ROW]
    )
    EXPORT = BloomerpPermissionDefinition(
        name="Export",
        codename="export",
        description="Permission to export records.",
        scopes=[PermissionScope.GLOBAL, PermissionScope.FIELD, PermissionScope.ROW]
    )
    IMPORT = BloomerpPermissionDefinition(
        name="Import",
        codename="import",
        description="Permission to import records.",
        scopes=[PermissionScope.GLOBAL, PermissionScope.FIELD, PermissionScope.ROW]
    )
    BULK_ADD = BloomerpPermissionDefinition(
        name="Bulk Add",
        codename="bulk_add",
        description="Permission to add multiple records at once.",
        scopes=[PermissionScope.GLOBAL, PermissionScope.FIELD, PermissionScope.ROW]
    )
    BULK_CHANGE = BloomerpPermissionDefinition(
        name="Bulk Change",
        codename="bulk_change",
        description="Permission to change multiple records at once.",
        scopes=[PermissionScope.GLOBAL, PermissionScope.FIELD]
    )
    BULK_DELETE = BloomerpPermissionDefinition(
        name="Bulk Delete",
        codename="bulk_delete",
        description="Permission to delete multiple records at once.",
        scopes=[PermissionScope.GLOBAL]
    )
    
    @classmethod
    def to_tuple(cls) -> tuple[str, ...]:
        """
        Returns a tuple of all permission codenames.
        """
        return tuple(permission.value.codename for permission in cls)


class RowPolicyRuleCondition(BaseModel):
    """Legacy input adapter; new code should construct FilterCondition instead."""
    application_field_id: Optional[int | str] = None
    operator: Optional[str] = None
    value: Optional[Any] = None
    field: Optional[str] = None

    @model_validator(mode="after")
    def validate_condition_shape(self):
        if self.field == "__all__" or self.application_field_id == "__all__":
            return self

        if self.application_field_id in (None, "") and self.field in (None, ""):
            raise ValueError("Missing application field id or field name in rule")
        if self.operator in (None, ""):
            raise ValueError("Missing operator")
        if self.value is None or self.value == "":
            raise ValueError("No value given")

        return self


class RowPolicyRuleContent(Filter):
    """A shared filter predicate with the grants that it enables.

    Empty AND/OR groups have exactly the same semantics as ordinary filters.
    Legacy condition objects are accepted only as migration input.
    """
    connector: Literal["AND", "OR"] = "AND"
    permissions: list[BloomerpPermission | str] = Field(default_factory=list)
    _legacy_content_type_ids: set[int] = PrivateAttr(default_factory=set)

    @model_validator(mode="wrap")
    @classmethod
    def normalize_legacy_conditions(cls, data, handler):
        from bloomerp.permissions.legacy import normalize_condition

        if isinstance(data, cls):
            return handler(data)
        normalized = dict(data)
        connector = normalized.get("connector", "AND")
        if connector not in {"AND", "OR"}:
            raise ValueError("Invalid filter connector")
        # Read rules saved during the earlier draft; never serialize this flag.
        old_match_all = normalized.pop("match_all", False)
        if not isinstance(old_match_all, bool):
            raise ValueError("Invalid legacy match_all flag")
        if old_match_all and normalized.get("conditions"):
            raise ValueError("An unconditional grant cannot also contain conditions")
        conditions, scopes, unconditional = [], set(), old_match_all
        for condition in normalized.get("conditions", []):
            condition, scope = normalize_condition(condition)
            if scope is not None:
                scopes.add(scope)
            if condition is None:
                unconditional = True
            else:
                conditions.append(condition)
        if unconditional:
            if connector == "OR" and conditions:
                raise ValueError("Rewrite mixed legacy __all__ OR rules as an explicit empty AND group")
            if not conditions:
                normalized["connector"] = "AND"
        normalized["conditions"] = conditions
        result = handler(normalized)
        result._legacy_content_type_ids = scopes
        return result


class AccessRule(BaseModel):
    row_permissions: list[RowPolicyRuleContent] = Field(default_factory=list)
    field_permissions: dict[str, list[BloomerpPermission | str]] = Field(default_factory=dict)
    
    
