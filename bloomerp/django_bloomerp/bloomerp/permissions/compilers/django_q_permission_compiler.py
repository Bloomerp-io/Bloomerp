from dataclasses import dataclass

from django.db.models import Q

from bloomerp.field_types.lookups import Lookup
from bloomerp.models.application_field import ApplicationField
from bloomerp.permissions.compilers.base import BasePermissionCompiler
from bloomerp.permissions.definition import (
    PermissionMatch,
    RowPolicyRuleCondition,
    RowPolicyRuleContent,
)


@dataclass(frozen=True)
class CompiledDjangoAccess:
    row_filter: Q
    field_filters: dict[Q, list[ApplicationField]]


class DjangoQPermissionCompiler(BasePermissionCompiler[CompiledDjangoAccess]):
    """Compile normalized access rules to Django ``Q`` expressions."""

    def compile_condition(
        self,
        condition: RowPolicyRuleCondition | dict,
        application_fields: dict[str, ApplicationField],
    ) -> Q | None:
        if isinstance(condition, dict):
            try:
                condition = RowPolicyRuleCondition.model_validate(condition)
            except Exception:
                return None
        if not isinstance(condition, RowPolicyRuleCondition):
            return None
        if condition.field == "__all__" or condition.application_field_id == "__all__":
            return Q(pk__isnull=False)
        if not condition.application_field_id or not condition.operator:
            return None

        application_field = application_fields.get(str(condition.application_field_id))
        if application_field is None:
            return None
        operator = str(condition.operator)
        field_name = application_field.field
        if isinstance(condition.field, str) and "__" in condition.field:
            field_name = condition.field

        if operator.startswith("__"):
            filter_key = operator.lstrip("_")
            lookup_name = filter_key.rsplit("__", 1)[-1]
            value = self.normalize_lookup_value(
                application_field,
                lookup_name,
                condition.value,
            )
            return Q(**{filter_key: value})

        if (
            self.resolve_lookup_globally(operator) == Lookup.EQUALS_USER
            or str(condition.value) == "$user"
        ):
            if self.user is None or getattr(self.user, "is_anonymous", False):
                return None
            return Q(**{field_name: self.user})

        lookup = self.resolve_lookup(application_field, operator)
        if lookup is not None:
            value = self.normalize_lookup_value(
                application_field,
                lookup,
                condition.value,
            )
            if lookup == Lookup.NOT_EQUALS:
                return ~Q(**{field_name: value})
            django_lookup = (lookup.value.django_representation or "").strip()
            filter_key = (
                f"{field_name}__{django_lookup}"
                if django_lookup
                else field_name
            )
            return Q(**{filter_key: value})

        from bloomerp.utils.filters import resolve_filter

        model = application_field.content_type.model_class()
        resolved_filter = resolve_filter(
            model,
            application_field,
            field_name,
            operator,
        )
        if resolved_filter is None:
            return None
        _filter_key, configured_filter = resolved_filter
        if hasattr(configured_filter, "as_q"):
            try:
                value = configured_filter.field.clean(condition.value)
            except Exception:
                return None
            return configured_filter.as_q(value)
        return None

    def compile_row_rule(
        self,
        row_rule: RowPolicyRuleContent | dict,
        application_fields: dict[str, ApplicationField],
    ) -> Q | None:
        if isinstance(row_rule, dict):
            try:
                row_rule = RowPolicyRuleContent.model_validate(row_rule)
            except Exception:
                return None
        if not isinstance(row_rule, RowPolicyRuleContent) or not row_rule.conditions:
            return None
        filters = []
        for condition in row_rule.conditions:
            condition_filter = self.compile_condition(condition, application_fields)
            if condition_filter is None:
                return None
            filters.append(condition_filter)
        combined = filters[0]
        for condition_filter in filters[1:]:
            combined = (
                combined | condition_filter
                if row_rule.connector == "OR"
                else combined & condition_filter
            )
        return combined

    def compile(
        self,
        permissions,
        match: PermissionMatch = PermissionMatch.ANY,
    ) -> CompiledDjangoAccess:
        rules = self.normalize_access_rules(self.rules)
        requested = self.normalize_permissions(permissions)
        application_fields = self.get_application_fields(rules)
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
