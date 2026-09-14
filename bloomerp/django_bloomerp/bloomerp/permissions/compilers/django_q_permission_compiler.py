from dataclasses import dataclass

from django.db.models import Q

from bloomerp.models.application_field import ApplicationField
from bloomerp.permissions.compilers.base import BasePermissionCompiler
from bloomerp.permissions.definition import (
    PermissionMatch,
    RowPolicyRuleContent,
)


@dataclass(frozen=True)
class CompiledDjangoAccess:
    row_filter: Q
    field_filters: dict[Q, list[ApplicationField]]


class DjangoQPermissionCompiler(BasePermissionCompiler[CompiledDjangoAccess]):
    """Compile normalized access rules to Django ``Q`` expressions."""

    def compile_row_rule(self, row_rule, application_fields=None) -> Q | None:
        """Permission failures deny this grant; predicate semantics are shared."""
        from django.core.exceptions import ValidationError
        from bloomerp.filters.compiler import compile_filters

        try:
            if not isinstance(row_rule, RowPolicyRuleContent):
                row_rule = RowPolicyRuleContent.model_validate(row_rule)
            predicate = self.prepare_row_filter(row_rule)
            return compile_filters([predicate], model=self.model).predicate
        except (ValidationError, ValueError, TypeError):
            return None

    def compile(
        self,
        permissions,
        match: PermissionMatch = PermissionMatch.ANY,
    ) -> CompiledDjangoAccess:
        rules = self.normalize_access_rules(self.rules)
        requested = self.normalize_permissions(permissions)
        application_fields = self.get_application_fields(rules, self.model)
        row_filters: list[Q] = []
        field_filters: dict[Q, list[ApplicationField]] = {}

        for rule in rules:
            rule_filters = []
            for row_rule in rule.row_permissions:
                if not self.matches_requested_permissions(
                    row_rule.permissions,
                    requested,
                    match,
                ):
                    continue
                row_filter = self.compile_row_rule(row_rule, application_fields)
                if row_filter is not None:
                    rule_filters.append(row_filter)
            if not rule_filters:
                continue
            rule_filter = rule_filters[0]
            for row_filter in rule_filters[1:]:
                rule_filter |= row_filter
            row_filters.append(rule_filter)

            accessible_fields = []
            seen_ids = set()
            for field_id, granted in rule.field_permissions.items():
                if not self.matches_requested_permissions(granted, requested, match):
                    continue
                if field_id == "__all__":
                    for field in application_fields.values():
                        if field.pk not in seen_ids:
                            accessible_fields.append(field)
                            seen_ids.add(field.pk)
                    continue
                field = application_fields.get(str(field_id))
                if field is not None and field.pk not in seen_ids:
                    accessible_fields.append(field)
                    seen_ids.add(field.pk)
            existing = field_filters.setdefault(rule_filter, [])
            existing_ids = {field.pk for field in existing}
            existing.extend(field for field in accessible_fields if field.pk not in existing_ids)

        if not row_filters:
            return CompiledDjangoAccess(Q(pk__in=[]), {})
        combined_filter = row_filters[0]
        for row_filter in row_filters[1:]:
            combined_filter |= row_filter
        return CompiledDjangoAccess(combined_filter, field_filters)
