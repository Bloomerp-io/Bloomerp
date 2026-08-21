from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from bloomerp.field_types.lookups import Lookup
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

    def __init__(self, rules, *, user=None):
        self.rules = rules
        self.user = user

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
    ) -> Lookup | None:
        if not application_field or not operator:
            return None
        field_type = application_field.get_field_type_enum()
        lookup = field_type.get_lookup_by_id(operator)
        if lookup is not None:
            return lookup
        for candidate in field_type.lookups:
            definition = candidate.value
            if operator == definition.django_representation:
                return candidate
            if operator in (definition.aliases or []):
                return candidate
        return None

    @staticmethod
    def resolve_lookup_globally(operator: str) -> Lookup | None:
        normalized = str(operator or "").lstrip("_")
        for lookup in Lookup:
            definition = lookup.value
            aliases = {str(alias).lstrip("_") for alias in definition.aliases or []}
            if normalized in {
                definition.id,
                str(definition.django_representation or "").lstrip("_"),
                *aliases,
            }:
                return lookup
        return None

    @staticmethod
    def normalize_lookup_value(
        application_field: ApplicationField,
        lookup: Lookup | str | None,
        value: Any,
    ) -> Any:
        lookup_name = (
            lookup.value.django_representation
            if isinstance(lookup, Lookup)
            else str(lookup or "")
        ).lower()
        if lookup_name == "in":
            if isinstance(value, str):
                return [item.strip() for item in value.split(",") if item.strip()]
            if isinstance(value, (tuple, set)):
                return list(value)
        if lookup_name == "isnull":
            if isinstance(value, str):
                return BOOLEAN_NORMALIZATION.get(value.strip().lower(), False)
            return bool(value)
        if application_field.field_type in {"BooleanField", "NullBooleanField"}:
            if isinstance(value, str):
                return BOOLEAN_NORMALIZATION.get(value.strip().lower(), False)
            return bool(value)
        return value

    @staticmethod
    def get_application_fields(rules: list[AccessRule]) -> dict[str, ApplicationField]:
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
        valid_ids = []
        for field_id in referenced_ids:
            try:
                valid_ids.append(ApplicationField._meta.pk.to_python(field_id))
            except (TypeError, ValueError):
                continue
        return {
            str(field.pk): field
            for field in ApplicationField.objects.filter(
                pk__in=valid_ids
            ).select_related("content_type", "related_model")
        }
