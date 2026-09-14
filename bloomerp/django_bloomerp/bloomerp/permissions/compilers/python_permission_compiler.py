from dataclasses import dataclass
from typing import Any, Callable

from django.core.exceptions import ObjectDoesNotExist
from django.db import models

from bloomerp.permissions.compilers.base import BasePermissionCompiler
from bloomerp.permissions.definition import PermissionMatch


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
            try:
                value = value.get(part, MISSING) if isinstance(value, dict) else getattr(value, part)
            except (AttributeError, ObjectDoesNotExist):
                return MISSING
        return value

    def compile(
        self,
        permissions,
        match: PermissionMatch = PermissionMatch.ANY,
    ) -> CompiledPythonAccess:
        rules = self.normalize_access_rules(self.rules)
        requested = self.normalize_permissions(permissions)
        from django.core.exceptions import ValidationError
        from bloomerp.filters.compiler import resolve_condition

        predicates = []
        for access_rule in rules:
            for row_rule in access_rule.row_permissions:
                if not self.matches_requested_permissions(row_rule.permissions, requested, match):
                    continue
                try:
                    predicate = self.prepare_row_filter(row_rule)
                    resolved = [resolve_condition(condition, model=self.model) for condition in predicate.conditions]
                    if any(lookup.get_python_evaluator() is None for _, _, lookup, _ in resolved):
                        continue
                except (ValidationError, ValueError, TypeError):
                    continue
                predicates.append((predicate.connector, resolved))

        def evaluator(candidate: models.Model) -> bool:
            if not isinstance(candidate, self.model):
                return False
            for connector, conditions in predicates:
                results = []
                for _, target, lookup, expected in conditions:
                    actual = self._resolve_value(candidate, target.field_path)
                    if actual is MISSING:
                        break
                    try:
                        result = lookup.get_python_evaluator()(
                            self._normalize_comparison_value(actual),
                            self._normalize_comparison_value(expected),
                        )
                    except (TypeError, ValueError, AttributeError):
                        break
                    results.append(bool(result))
                else:
                    matches = any(results) if connector == "OR" else all(results)
                    if matches:
                        return True
            return False

        return CompiledPythonAccess(evaluator=evaluator)
