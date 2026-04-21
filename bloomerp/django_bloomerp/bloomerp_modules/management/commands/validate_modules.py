from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import importlib
from typing import Any

import yaml
from django.core.management.base import BaseCommand

from bloomerp.field_types import FieldType


@dataclass
class ValidationIssue:
    module_id: str
    message: str


class Command(BaseCommand):
    help = "Validate module YAML specs and report any issues."

    def handle(self, *args, **options):
        modules_dir = Path(__file__).parent.parent.parent / "modules"
        if not modules_dir.exists():
            self.stdout.write(self.style.ERROR(f"Modules directory not found: {modules_dir}"))
            return

        issues = self._validate_modules_directory(modules_dir)
        self._render_report(issues)

    def _validate_modules_directory(self, modules_dir: Path) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for module_dir in sorted(item for item in modules_dir.iterdir() if item.is_dir()):
            self._validate_module_tree(module_dir, None, issues)
        return issues

    def _validate_module_tree(
        self,
        module_dir: Path,
        parent_module_id: str | None,
        issues: list[ValidationIssue],
    ) -> None:
        config_path = module_dir / "config.yaml"
        module_id = module_dir.name

        if not config_path.exists():
            issues.append(ValidationIssue(module_id, f"Module '{module_dir.name}' missing config.yaml"))
            return

        module_data = self._load_yaml(config_path, module_id, issues)
        if not isinstance(module_data, dict):
            return

        self._require_keys(module_data, ["id", "name", "code"], module_id, issues, "module config")
        module_id = module_data.get("id", module_id)

        declared_parent = module_data.get("parent_module_id")
        if parent_module_id and declared_parent and declared_parent != parent_module_id:
            issues.append(
                ValidationIssue(
                    module_id,
                    f"module config parent_module_id '{declared_parent}' does not match directory parent '{parent_module_id}'",
                )
            )

        for model_file in sorted(module_dir.glob("*.yaml")):
            if model_file.name == "config.yaml":
                continue
            self._validate_model_file(module_id, model_file, issues)

        for child_dir in sorted(item for item in module_dir.iterdir() if item.is_dir()):
            self._validate_module_tree(child_dir, module_id, issues)

    def _validate_model_file(
        self,
        module_id: str,
        model_file: Path,
        issues: list[ValidationIssue],
    ) -> None:
        model_data = self._load_yaml(model_file, module_id, issues)
        if model_data is None:
            return
        if not isinstance(model_data, dict):
            issues.append(ValidationIssue(module_id, f"Model '{model_file.name}' is not a mapping"))
            return

        self._require_keys(
            model_data,
            ["id", "name", "fields"],
            module_id,
            issues,
            f"model '{model_file.stem}'",
        )
        fields = model_data.get("fields")
        if not isinstance(fields, list):
            issues.append(ValidationIssue(module_id, f"Model '{model_file.stem}' fields must be a list"))
            return

        for index, field in enumerate(fields):
            field_context = f"model '{model_file.stem}' field #{index + 1}"
            if not isinstance(field, dict):
                issues.append(ValidationIssue(module_id, f"{field_context} is not a mapping"))
                continue
            self._require_keys(field, ["id", "name", "type"], module_id, issues, field_context)
            field_type = field.get("type")
            if isinstance(field_type, str):
                self._validate_field_type(field_type, module_id, issues, field_context)
            else:
                issues.append(ValidationIssue(module_id, f"{field_context} type must be a string"))
            self._validate_validator_paths(field, module_id, issues, field_context)

    def _validate_field_type(
        self,
        field_type: str,
        module_id: str,
        issues: list[ValidationIssue],
        context: str,
    ) -> None:
        try:
            field_definition = FieldType.from_id(field_type).value
        except ValueError as exc:
            issues.append(ValidationIssue(module_id, f"{context} has unknown type '{field_type}': {exc}"))
            return

        if not field_definition.allow_in_model:
            issues.append(ValidationIssue(module_id, f"{context} type '{field_type}' is not allowed in models"))

    def _validate_validator_paths(
        self,
        field: dict[str, Any],
        module_id: str,
        issues: list[ValidationIssue],
        context: str,
    ) -> None:
        validators = field.get("validators")
        if validators is None:
            return
        if not isinstance(validators, list):
            issues.append(ValidationIssue(module_id, f"{context} validators must be a list"))
            return

        for validator_path in validators:
            if not isinstance(validator_path, str):
                issues.append(ValidationIssue(module_id, f"{context} validator must be a string"))
                continue
            if "." not in validator_path:
                issues.append(ValidationIssue(module_id, f"{context} validator '{validator_path}' must be a dotted path"))
                continue
            module_path, function_name = validator_path.rsplit(".", 1)
            try:
                validator_module = importlib.import_module(module_path)
            except ImportError as exc:
                issues.append(ValidationIssue(module_id, f"{context} validator '{validator_path}' import failed: {exc}"))
                continue
            if not hasattr(validator_module, function_name):
                issues.append(ValidationIssue(module_id, f"{context} validator '{validator_path}' not found"))

    def _load_yaml(self, path: Path, module_id: str, issues: list[ValidationIssue]) -> Any:
        try:
            with path.open("r") as file:
                data = yaml.safe_load(file)
        except yaml.YAMLError as exc:
            issues.append(ValidationIssue(module_id, f"YAML parse error in {path}: {exc}"))
            return None
        except OSError as exc:
            issues.append(ValidationIssue(module_id, f"Could not read {path}: {exc}"))
            return None

        if data is None:
            issues.append(ValidationIssue(module_id, f"{path} is empty"))
            return None

        return data

    def _require_keys(
        self,
        data: dict[str, Any],
        keys: list[str],
        module_id: str,
        issues: list[ValidationIssue],
        context: str,
    ) -> None:
        for key in keys:
            if key not in data:
                issues.append(ValidationIssue(module_id, f"{context} missing required key '{key}'"))

    def _render_report(self, issues: list[ValidationIssue]) -> None:
        if not issues:
            self.stdout.write(self.style.SUCCESS("All module YAML specs are valid."))
            return

        issues_by_module: dict[str, list[ValidationIssue]] = defaultdict(list)
        for issue in issues:
            issues_by_module[issue.module_id].append(issue)

        self.stdout.write(self.style.WARNING("Module YAML validation report:"))
        for module_id, module_issues in sorted(issues_by_module.items()):
            self.stdout.write(self.style.ERROR(f"- {module_id}: {len(module_issues)} issue(s)"))
            for issue in module_issues:
                self.stdout.write(f"  - {issue.message}")
