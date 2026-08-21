from dataclasses import dataclass
from typing import Any, Callable

from django.core.exceptions import ObjectDoesNotExist
from django.db import models

from bloomerp.field_types.lookups import Lookup
from bloomerp.models.application_field import ApplicationField
from bloomerp.permissions.compilers.base import BasePermissionCompiler
from bloomerp.permissions.definition import PermissionMatch, RowPolicyRuleCondition


MISSING = object()


@dataclass(frozen=True)
class CompiledPythonAccess:
    evaluator: Callable[[models.Model], bool]

    def matches(self, candidate: models.Model) -> bool:
        return self.evaluator(candidate)


class PythonPermissionCompiler(BasePermissionCompiler[CompiledPythonAccess]):
    """Compile row policies to a fail-closed in-memory candidate evaluator."""

    @staticmethod
    def _normalize_comparison_value(value):
        if isinstance(value, models.Model):
            return value.pk
        if isinstance(value, models.Manager):
            value = value.all()
        if hasattr(value, "all") and callable(value.all):
            try:
                value = value.all()
            except Exception:
                pass
        if isinstance(value, models.QuerySet):
            value = list(value)
        if isinstance(value, (list, tuple, set, frozenset)):
            return [PythonPermissionCompiler._normalize_comparison_value(item) for item in value]
        return value

    @staticmethod
    def _resolve_value(
        candidate: models.Model,
        field_path: str,
    ):
        parts = [part for part in str(field_path or "").split("__") if part]
        if not parts:
            return MISSING
        first, *remaining = parts
        try:
            value = getattr(candidate, first)
        except (AttributeError, ObjectDoesNotExist):
            return MISSING
        for part in remaining:
            if value is None:
                return None
            if isinstance(value, dict):
                value = value.get(part, MISSING)
            else:
                try:
                    value = getattr(value, part)
                except (AttributeError, ObjectDoesNotExist):
                    return MISSING
            if value is MISSING:
                return MISSING
        return value

    @classmethod
    def _advanced_path_and_lookup(cls, operator: str) -> tuple[str, Lookup]:
        path = operator.lstrip("_")
        parts = [part for part in path.split("__") if part]
        if not parts:
            return "", Lookup.EQUALS
        lookup = cls.resolve_lookup_globally(parts[-1])
        if lookup is not None and lookup.value.python_eval is not None:
            parts.pop()
        else:
            lookup = Lookup.EQUALS
        return "__".join(parts), lookup

    @staticmethod
    def _coerce_expected_value(
        application_field: ApplicationField,
        lookup: Lookup,
        value,
    ):
        if isinstance(value, models.Model) or lookup in {
            Lookup.IS_NULL,
            Lookup.TODAY,
            Lookup.YESTERDAY,
            Lookup.THIS_WEEK,
            Lookup.LAST_WEEK,
            Lookup.THIS_MONTH,
            Lookup.LAST_MONTH,
            Lookup.THIS_QUARTER,
            Lookup.LAST_QUARTER,
            Lookup.THIS_YEAR,
            Lookup.LAST_YEAR,
            Lookup.YEAR,
            Lookup.MONTH,
            Lookup.DAY,
            Lookup.WEEK,
            Lookup.DAY_OF_WEEK,
            Lookup.DAY_OF_WEEK_IN,
        }:
            return value
        try:
            model_field = application_field._get_model_field()
            converter = getattr(model_field, "target_field", model_field).to_python
            if lookup == Lookup.IN and isinstance(value, (list, tuple, set, frozenset)):
                return [converter(item) for item in value]
            return converter(value)
        except Exception:
            return value

    def _evaluate_condition(
        self,
        condition: RowPolicyRuleCondition,
        candidate: models.Model,
        application_fields: dict[str, ApplicationField],
    ) -> bool | None:
        if condition.field == "__all__" or condition.application_field_id == "__all__":
            return True
        application_field = application_fields.get(str(condition.application_field_id))
        if application_field is None or not condition.operator:
            return None

        operator = str(condition.operator)
        advanced = operator.startswith("__")
        if advanced:
            field_path, lookup = self._advanced_path_and_lookup(operator)
        else:
            field_path = (
                condition.field
                if isinstance(condition.field, str) and "__" in condition.field
                else application_field.field
            )
            lookup = (
                Lookup.EQUALS_USER
                if self.resolve_lookup_globally(operator) == Lookup.EQUALS_USER
                or str(condition.value) == "$user"
                else (
                    self.resolve_lookup_globally(operator)
                    if "__" in str(condition.field or "")
                    else self.resolve_lookup(application_field, operator)
                )
            )
        if lookup is None or lookup.value.python_eval is None:
            return None

        actual = self._resolve_value(candidate, field_path)
        if actual is MISSING:
            return None
        expected = self.user if (
            lookup == Lookup.EQUALS_USER or str(condition.value) == "$user"
        ) else condition.value
        if expected is None and str(condition.value) == "$user":
            return None
        expected = self.normalize_lookup_value(application_field, lookup, expected)
        if not advanced and "__" not in str(condition.field or ""):
            expected = self._coerce_expected_value(application_field, lookup, expected)
        actual = self._normalize_comparison_value(actual)
        expected = self._normalize_comparison_value(expected)
        try:
            return bool(lookup.value.python_eval(actual, expected))
        except Exception:
            return None

    def compile(
        self,
        permissions,
        match: PermissionMatch = PermissionMatch.ANY,
    ) -> CompiledPythonAccess:
        rules = self.normalize_access_rules(self.rules)
        requested = self.normalize_permissions(permissions)
        application_fields = self.get_application_fields(rules)

        def evaluator(candidate: models.Model) -> bool:
            if not isinstance(candidate, models.Model):
                return False
            for access_rule in rules:
                for row_rule in access_rule.row_permissions:
                    if not self.matches_requested_permissions(
                        row_rule.permissions,
                        requested,
                        match,
                    ):
                        continue
                    condition_results = []
                    valid = True
                    for condition in row_rule.conditions:
                        result = self._evaluate_condition(
                            condition,
                            candidate,
                            application_fields,
                        )
                        if result is None:
                            valid = False
                            break
                        condition_results.append(result)
                    if not valid or not condition_results:
                        continue
                    if row_rule.connector == "OR":
                        if any(condition_results):
                            return True
                    elif all(condition_results):
                        return True
            return False

        return CompiledPythonAccess(evaluator=evaluator)
