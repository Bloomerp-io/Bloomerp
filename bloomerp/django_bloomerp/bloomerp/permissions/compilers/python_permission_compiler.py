from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.db import models

from bloomerp.permissions.compilers.base import BasePermissionCompiler
from bloomerp.permissions.definition import BloomerpPermission, PermissionMatch

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
    def _resolve_value(candidate: models.Model, field_path: str) -> Any:
        """Resolve scalar candidates and persisted multi-valued relationship paths."""
        parts = [part for part in str(field_path or "").split("__") if part]
        if not parts:
            return MISSING
        value: Any = candidate
        for index, part in enumerate(parts):
            if value is None:
                return None
            if isinstance(value, (models.Manager, models.QuerySet)):
                return value.all().values_list("__".join(parts[index:]), flat=True)
            try:
                value = value.get(part, MISSING) if isinstance(value, dict) else getattr(value, part)
            except (AttributeError, ObjectDoesNotExist):
                return MISSING
        return value

    def compile(
        self,
        permissions: str | BloomerpPermission | Iterable[str | BloomerpPermission] | None,
        match: PermissionMatch = PermissionMatch.ANY,
    ) -> CompiledPythonAccess:
        """Compile requested grants into an evaluator for scalar and related fields."""
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
            """Match a candidate against any compiled row grant, failing closed."""
            if not isinstance(candidate, self.model):
                return False
            for connector, conditions in predicates:
                results = []
                for _, target, lookup, expected in conditions:
                    actual = self._resolve_value(candidate, target.field_path)
                    if actual is MISSING:
                        break
                    try:
                        if isinstance(actual, (models.Manager, models.QuerySet)) and lookup.id in {"equals", "equals_user"}:
                            # A relational equality matches any related row, as its
                            # Django JOIN counterpart does; JSON lists remain scalar.
                            values = actual.all()
                            result = any(
                                self._normalize_comparison_value(value) == self._normalize_comparison_value(expected)
                                for value in values
                            )
                        else:
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
