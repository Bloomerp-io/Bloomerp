from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from django.core.exceptions import ValidationError

from bloomerp.lookups import builtins as lookups
from bloomerp.lookups.definition import LookupDefinition
from bloomerp.models.application_field import ApplicationField
from bloomerp.permissions.definition import (
    AccessRule,
    BloomerpPermission,
    PermissionMatch,
)


CompiledPermission = TypeVar("CompiledPermission")

BOOLEAN_NORMALIZATION = {
    "true": True,
    "1": True,
    "yes": True,
    "on": True,
    "false": False,
    "0": False,
    "no": False,
    "off": False,
}


class BasePermissionCompiler(ABC, Generic[CompiledPermission]):
    """Shared normalization and lookup behavior for permission compilers."""

    def __init__(self, rules, *, user=None, model=None):
        self.rules = rules
        self.user = user
        self.model = model

    @abstractmethod
    def compile(self, *args, **kwargs) -> CompiledPermission:
        raise NotImplementedError

    @staticmethod
    def normalize_access_rules(rules) -> list[AccessRule]:
        normalized: list[AccessRule] = []
        for rule in rules or []:
            if not isinstance(rule, AccessRule):
                try:
                    rule = AccessRule.model_validate(rule)
                except Exception:
                    continue
            normalized.append(rule)
        return normalized

    @staticmethod
    def normalize_permissions(permissions) -> list[str | BloomerpPermission]:
        if isinstance(permissions, (str, BloomerpPermission)):
            return [permissions]
        return list(permissions or [])

    @staticmethod
    def permission_codename(permission: str | BloomerpPermission) -> str:
        if isinstance(permission, BloomerpPermission):
            return permission.value.codename
        return str(permission).strip().rsplit(".", 1)[-1]

    @classmethod
    def permission_matches(cls, granted, requested) -> bool:
        granted_codename = cls.permission_codename(granted)
        requested_codename = cls.permission_codename(requested)
        if granted_codename == requested_codename:
            return True
        return (
            granted_codename.startswith(f"{requested_codename}_")
            or requested_codename.startswith(f"{granted_codename}_")
        )

    @classmethod
    def matches_requested_permissions(
        cls,
        granted,
        requested,
        match: PermissionMatch,
    ) -> bool:
        granted = list(granted or [])
        requested = cls.normalize_permissions(requested)
        if not requested:
            return bool(granted)
        checks = [
            any(cls.permission_matches(grant, permission) for grant in granted)
            for permission in requested
        ]
        return all(checks) if match == PermissionMatch.ALL else any(checks)

    @staticmethod
    def resolve_lookup(
        application_field: ApplicationField,
        operator: str,
    ) -> LookupDefinition | None:
        if not application_field or not operator:
            return None
        field_type = application_field.get_field_type()
        
        lookup = field_type.get_lookup_by_id(operator)
        if lookup is not None:
            return lookup
        normalized = str(operator).lstrip("_")
        for candidate in field_type.lookups:
            if normalized in candidate.expressions:
                return candidate
        return None

    @staticmethod
    def resolve_lookup_globally(operator: str) -> LookupDefinition | None:
        from bloomerp.lookups.registry import LOOKUP_REGISTRY

        normalized = str(operator or "").lstrip("_")
        for lookup in LOOKUP_REGISTRY.values():
            if normalized == lookup.id or normalized in lookup.expressions:
                return lookup
        return None

    @staticmethod
    def normalize_lookup_value(
        application_field: ApplicationField,
        lookup: LookupDefinition | str | None,
        value: Any,
    ) -> Any:
        lookup_name = (
            lookup.id
            if isinstance(lookup, LookupDefinition)
            else str(lookup or "")
        ).lower()
        if lookup_name in {"in", "values_in"}:
            if isinstance(value, str):
                return [item.strip() for item in value.split(",") if item.strip()]
            if isinstance(value, (tuple, set)):
                return list(value)
        if lookup_name in {"isnull", "is_null"}:
            if isinstance(value, str):
                return BOOLEAN_NORMALIZATION.get(value.strip().lower(), False)
            return bool(value)
        if application_field.field_type in {"BooleanField", "NullBooleanField"}:
            if isinstance(value, str):
                return BOOLEAN_NORMALIZATION.get(value.strip().lower(), False)
            return bool(value)
        return value

    @staticmethod
    def get_application_fields(
        rules: list[AccessRule],
        model=None,
    ) -> dict[str, ApplicationField]:
        referenced_ids = {
            str(condition.application_field_id)
            for rule in rules
            for row_rule in rule.row_permissions
            for condition in row_rule.conditions
            if condition.application_field_id not in (None, "", "__all__")
        }
        referenced_ids.update(
            str(field_id)
            for rule in rules
            for field_id in rule.field_permissions
            if field_id != "__all__"
        )
        referenced_names = {
            str(condition.field).replace(".", "__").split("__", 1)[0]
            for rule in rules
            for row_rule in rule.row_permissions
            for condition in row_rule.conditions
            if condition.field not in (None, "", "__all__")
        }
        referenced_names.update(
            str(field_name).replace(".", "__").split("__", 1)[0]
            for rule in rules
            for field_name in rule.field_permissions
            if field_name != "__all__" and not str(field_name).isdigit()
        )
        valid_ids = []
        for field_id in referenced_ids:
            try:
                valid_ids.append(ApplicationField._meta.pk.to_python(field_id))
            except (TypeError, ValueError, ValidationError):
                continue
        queryset = ApplicationField.objects.filter(pk__in=valid_ids)
        if model is not None:
            from django.contrib.contenttypes.models import ContentType

            content_type = ContentType.objects.get_for_model(model)
            model_fields = ApplicationField.objects.filter(content_type=content_type)
            if any("__all__" in rule.field_permissions for rule in rules):
                queryset = queryset | model_fields
            elif referenced_names:
                queryset = queryset | model_fields.filter(field__in=referenced_names)

        fields = list(queryset.distinct())
        resolved = {
            str(field.pk): field
            for field in fields
        }
        resolved.update({field.field: field for field in fields})
        return resolved
