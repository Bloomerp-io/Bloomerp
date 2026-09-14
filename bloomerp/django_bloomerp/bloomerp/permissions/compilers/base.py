from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from django.core.exceptions import ValidationError

from bloomerp.models.application_field import ApplicationField
from bloomerp.permissions.definition import (
    AccessRule,
    BloomerpPermission,
    PermissionMatch,
)


CompiledPermission = TypeVar("CompiledPermission")

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

    def prepare_row_filter(self, row_rule):
        """Bind permission-owned runtime values before shared compilation."""
        from django.contrib.contenttypes.models import ContentType
        from bloomerp.filters.definition import Filter

        scope_id = ContentType.objects.get_for_model(self.model).pk
        if row_rule._legacy_content_type_ids - {scope_id}:
            raise ValidationError("Legacy rule references a different content type")
        conditions = []
        for condition in row_rule.conditions:
            if condition.value == "$user" or condition.lookup_id == "equals_user":
                if self.user is None or getattr(self.user, "is_anonymous", False):
                    raise ValidationError("Current-user condition requires a user")
                condition = condition.model_copy(update={"value": self.user.pk})
            conditions.append(condition)
        return Filter(connector=row_rule.connector, conditions=conditions)

    @staticmethod
    def get_application_fields(
        rules: list[AccessRule],
        model=None,
    ) -> dict[str, ApplicationField]:
        referenced_ids = set()
        referenced_ids.update(
            str(field_id)
            for rule in rules
            for field_id in rule.field_permissions
            if field_id != "__all__"
        )
        referenced_names = {
            condition.field_path.split("__", 1)[0]
            for rule in rules
            for row_rule in rule.row_permissions
            for condition in row_rule.conditions
            if condition.field_path
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
