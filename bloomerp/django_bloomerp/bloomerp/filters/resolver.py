"""Shared field discovery and resolution for editors and condition compilers."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from django.core.exceptions import FieldDoesNotExist, PermissionDenied, ValidationError
from django.db.models import Expression, F, Model
from django.db.models.fields.json import KeyTransform
from django.utils.translation import gettext as _

from bloomerp.filters.definition import FilterField, FilterFieldGroup
from bloomerp.lookups.definition import BoundLookup, SQLLookupContext


@dataclass(frozen=True)
class FilterExecutionTarget:
    backend: Literal["django", "sql"]
    field_path: str
    model: type[Model] | None = None
    tile_id: str | None = None
    sql_context: SQLLookupContext | None = None
    orm_expression: Expression | None = None


def resolve_lookup(
    field: FilterField, target: FilterExecutionTarget, lookup_id: str,
) -> BoundLookup:
    """Resolve a supported lookup for the field and execution backend."""
    for lookup in field.context.field_type.lookups:
        bound = BoundLookup.normalize(lookup)
        if bound.id == lookup_id:
            if target.backend == "sql" and not bound.nested and bound.get_sql_factory() is None:
                raise ValidationError("This lookup does not support analytics filtering")
            return bound
    raise ValidationError("Lookup is not available for this field")


class FilterFieldResolver:
    """Resolve within a scope, optionally enforcing the requesting user's access.

    UI callers use for_user(). Trusted policy compilation uses for_model() to
    resolve structural metadata without recursively evaluating field policies.
    Paths use Django's __ separator. Workspace roots are shared:<key> or
    tile_<id>:<field>. Execution consumers expand shared paths with resolve_all().
    """

    def __init__(self, *, model=None, workspace=None, fields=None, policy_manager=None):
        if sum(value is not None for value in (model, workspace, fields)) != 1:
            raise ValueError("Supply exactly one model, workspace, or field collection")
        self.model = model
        self.workspace = workspace
        self.policy_manager = policy_manager
        self._allowed_fields = {}
        self._roots = [("Fields", field, None) for field in fields] if fields is not None else None
        self._shared_keys = {}
        self._shared = None

    @classmethod
    def for_fields(cls, fields):
        """Resolve configured result columns without a Django model."""
        return cls(fields=fields)

    @classmethod
    def for_model(cls, model):
        return cls(model=model)

    @classmethod
    def for_user(cls, scope:Literal['workspace', 'model'], identifier:str|int, user):
        from django.shortcuts import get_object_or_404
        from bloomerp.models.workspaces.workspace import Workspace
        from bloomerp.permissions.definition import BloomerpPermission
        from bloomerp.permissions.manager import UserPolicyManager
        from bloomerp.utils.models import get_model_and_content_type_or_404
        from bloomerp.workspaces.utils import has_access_to_workspace

        if not identifier:
            raise ValidationError("A scope id is required")
        manager = UserPolicyManager(user)
        if scope == "model":
            model, content_type = get_model_and_content_type_or_404(identifier)
            if not manager.has_global_permission(content_type, BloomerpPermission.VIEW):
                raise PermissionDenied
            return cls(model=model, policy_manager=manager)
        if scope == "workspace":
            workspace = get_object_or_404(Workspace, pk=identifier)
            if not has_access_to_workspace(workspace, user):
                raise PermissionDenied
            return cls(workspace=workspace.effective_preference, policy_manager=manager)
        raise ValidationError("Scope must be model or workspace")

    def _can_access(self, field):
        application_field = field.context.application_field
        if self.policy_manager is None or application_field is None:
            return True
        from bloomerp.permissions.definition import BloomerpPermission
        key = application_field.content_type_id
        if key not in self._allowed_fields:
            self._allowed_fields[key] = set(self.policy_manager.get_accessible_fields(
                application_field.content_type, BloomerpPermission.VIEW,
            ).values_list("pk", flat=True))
        return application_field.pk in self._allowed_fields[key]

    def _root_fields(self):
        if self._roots is not None:
            return self._roots
        from bloomerp.filters.utils import application_fields_to_filter_field_groups
        from bloomerp.models.application_field import ApplicationField

        roots = []
        if self.model is not None:
            for group in application_fields_to_filter_field_groups(ApplicationField.get_for_model(self.model)):
                for field in group.fields:
                    roots.append((group.name, field, None))
        else:
            for tile in self.workspace.get_tiles():
                definition = tile.get_tile_type_definition()
                config = tile.get_config_object()
                for field in definition.filter_fields_factory(config):
                    key = config.get_filter_shared_key(field.field)
                    if key is not None and (not key or ":" in key):
                        raise ValidationError("Shared filter keys must be nonempty names without :")
                    self._shared_keys[(str(tile.pk), field.field)] = key
                    roots.append((str(tile.title) if hasattr(tile, "title") else str(tile), field, str(tile.pk)))
        self._roots = [(group, field, tile) for group, field, tile in roots if self._can_access(field)]
        return self._roots

    def discover(self, field_path=None, lookup_id=None) -> list[FilterFieldGroup]:
        if bool(field_path) != bool(lookup_id):
            raise ValidationError("Nested discovery requires field_path and lookup_id")
        if field_path:
            resolved = self.resolve_all(field_path)
            child_groups = [self._children(parent, target, lookup_id) for parent, target in resolved]
            if len(child_groups) == 1:
                return child_groups[0]
            common = None
            for groups in child_groups:
                keys = {(field.field, self._sharing_signature(field)) for group in groups for field in group.fields}
                common = keys if common is None else common & keys
            return [FilterFieldGroup(name=group.name, fields=fields)
                    for group in child_groups[0]
                    if (fields := [field for field in group.fields if (field.field, self._sharing_signature(field)) in common])]
        groups = {}
        shared = self._shared_fields()
        shared_members = {(tile, field.field) for members in shared.values() for _, field, tile in members}
        if shared:
            groups[_("Shared fields")] = [
                self._shared_editor_field(key, members)
                for key, members in shared.items()
            ]
        for name, field, tile in self._root_fields():
            if (tile, field.field) in shared_members:
                continue
            path = f"tile_{tile}:{field.field}" if tile else field.field
            groups.setdefault(name, []).append(field.model_copy(update={"field": path}))
        return [FilterFieldGroup(name=name, fields=fields) for name, fields in groups.items()]

    @staticmethod
    def _sharing_signature(field):
        """Configuration checks belong to workspace resolution, not FieldType."""
        application_field = field.context.application_field
        related_model = None
        choices = None
        if application_field is not None:
            related_model = application_field.related_model_id
            try:
                model_field = application_field._get_model_field()
            except FieldDoesNotExist:
                # Virtual fields have no configuration we can safely compare.
                return field.context.field_type.id, ("virtual", application_field.pk), None
            if getattr(model_field, "choices", None):
                choices = tuple((str(value), str(label)) for value, label in model_field.flatchoices)
        return field.context.field_type.id, related_model, choices

    def _shared_fields(self):
        if self._shared is not None:
            return self._shared
        candidates = {}
        for member in self._root_fields():
            _, field, tile = member
            if tile is None:
                continue
            key = self._shared_keys.get((tile, field.field), field.field)
            if key is not None:
                candidates.setdefault(key, []).append(member)
        self._shared = {}
        for key, members in candidates.items():
            # A shared identity must resolve to exactly one field per tile.
            if len(members) < 2 or len({tile for _, _, tile in members}) != len(members):
                continue
            if len({self._sharing_signature(field) for _, field, _ in members}) == 1:
                self._shared[key] = members
        return self._shared

    def _shared_editor_field(self, key, members):
        field = members[0][1]
        _, related_model, choices = self._sharing_signature(field)
        context = field.context
        if related_model is None and choices is None:
            context = replace(context, application_field=None)
        return field.model_copy(update={"field": f"shared:{key}", "label": key.replace("_", " ").title(), "context": context})

    def resolve_all(self, field_path: str) -> list[tuple[FilterField, FilterExecutionTarget]]:
        """Resolve a logical workspace field to every participating tile target."""
        if not isinstance(field_path, str) or not field_path.startswith("shared:"):
            return [self._resolve(field_path, [])]
        path = field_path[7:]
        matches = [key for key in self._shared_fields() if path == key or path.startswith(key + "__")]
        if not matches:
            raise ValidationError("Shared field is unknown or inaccessible")
        key = max(matches, key=len)
        suffix = path[len(key):]
        members = self._shared_fields()[key]
        results = [self._resolve(f"tile_{tile}:{field.field}" + suffix, [])
                   for _, field, tile in members]
        if len({self._sharing_signature(field) for field, _ in results}) != 1:
            raise ValidationError("Nested shared fields have incompatible configurations")
        return results

    def resolve_for_tile(self, field_path: str, tile_id: str):
        """Return this tile's target, or None when the field does not apply."""
        return next((result for result in self.resolve_all(field_path)
                     if result[1].tile_id == str(tile_id)), None)

    def _children(self, parent: FilterField, target: FilterExecutionTarget, lookup_id):
        bound = resolve_lookup(parent, target, lookup_id)
        factory = bound.lookup.nested_fields_factory
        if not bound.nested or factory is None:
            raise ValidationError("Lookup does not support field discovery")
        groups = factory(target.model, target.field_path)
        result = []
        for group in groups:
            fields = [field for field in group.fields if self._can_access(field)]
            if fields:
                result.append(FilterFieldGroup(name=group.name, fields=fields))
        return result

    def resolve_dependencies(self, field_path: str) -> list[FilterField]:
        """Return each traversed field using the same resolution as compilation."""
        dependencies = []
        for field, target in self.resolve_all(field_path):
            path = f"tile_{target.tile_id}:{target.field_path}" if target.tile_id else field_path
            self._resolve(path, dependencies)
        return dependencies

    def resolve(self, field_path: str) -> tuple[FilterField, FilterExecutionTarget]:
        results = self.resolve_all(field_path)
        if not field_path.startswith("shared:"):
            return results[0]
        # Discovery/editor callers use the most restrictive backend capability.
        field, target = next((item for item in results if item[1].backend == "sql"), results[0])
        context = field.context
        _, related_model, choices = self._sharing_signature(field)
        if related_model is None and choices is None:
            context = replace(context, application_field=None)
        return field.model_copy(update={"field": field_path, "context": context}), target

    def _resolve(self, field_path: str, dependencies: list[FilterField]) -> tuple[FilterField, FilterExecutionTarget]:
        """Return field metadata and its separate execution target."""
        if not isinstance(field_path, str) or not field_path or len(field_path) > 2048:
            raise ValidationError("Invalid field path")
        # Match complete configured roots first; analytics aliases may contain __.
        candidates = []
        for _, field, tile in self._root_fields():
            root = f"tile_{tile}:{field.field}" if tile else field.field
            if field_path == root or field_path.startswith(root + "__"):
                candidates.append((root, field, tile))
        if not candidates:
            raise ValidationError("Field is unknown or inaccessible in this scope")
        root, field, tile = max(candidates, key=lambda item: len(item[0]))
        if sum(item[0] == root for item in candidates) != 1:
            raise ValidationError("Ambiguous field path")
        context = field.context
        application_field = context.application_field
        model = self.model or (application_field.get_model() if application_field else None)
        sql_context = None
        if model is None:
            # Quote a configured result-column alias, never accept SQL from the request.
            sql_context = SQLLookupContext(field_path='"' + field.field.replace('"', '""') + '"')
        target = FilterExecutionTarget(
            backend="django" if model else "sql", model=model,
            field_path=field.field, tile_id=tile, sql_context=sql_context,
        )
        current = field.model_copy(update={"field": root})
        dependencies.append(current)
        suffix = field_path[len(root):]
        parts = suffix[2:].split("__") if suffix else []
        if len(parts) > 32 or any(not part for part in parts):
            raise ValidationError("Invalid or excessively deep field path")
        for part in parts:
            nested = [BoundLookup.normalize(item) for item in current.context.field_type.lookups if item.nested]
            if len(nested) != 1:
                raise ValidationError("Field traversal requires one unambiguous nested lookup")
            children = [field for group in self._children(current, target, nested[0].id) for field in group.fields]
            child = next((field for field in children if field.field == part), None)
            if child is None:
                child = next((field for field in children if field.field == ""), None)
            if child is None:
                raise ValidationError("Nested field is unknown or inaccessible")
            context = child.context
            orm_expression = None
            if child.field == "":
                # Preserve the source ApplicationField for lookup coercion, but
                # use the JSON editor supplied by the child descriptor.
                context = replace(context, application_field=current.context.application_field)
                if target.backend == "django":
                    orm_expression = KeyTransform(part, target.orm_expression if target.orm_expression is not None else F(target.field_path))
            sql_context = target.sql_context
            if sql_context is not None:
                # JSON child names are quoted as string data within the SQL expression.
                key = part.replace("\\", "\\\\").replace("'", "''")
                if "\x00" in key:
                    raise ValidationError("Invalid JSON key")
                sql_context = replace(sql_context, field_path=f"({sql_context.field_path} -> E'{key}')")
            target = replace(target, field_path=target.field_path + "__" + part, sql_context=sql_context, orm_expression=orm_expression)
            current = child.model_copy(update={
                "field": current.field + "__" + part,
                "label": child.label if child.field else part,
                "context": context,
            })
            dependencies.append(current)
        return current, target


def resolve_filter_field(*, scope, identifier, field_path, user):
    return FilterFieldResolver.for_user(scope, identifier, user).resolve(field_path)


def filters_for_tile(filters, *, tile_id, resolver=None):
    """Translate workspace identities to local paths, preserving applicable groups."""
    from bloomerp.filters.definition import Filter

    groups = []
    for group in filters:
        conditions = []
        for condition in group.conditions:
            path = condition.field_path
            if path.startswith("shared:") or (path.startswith("tile_") and ":" in path):
                if not tile_id:
                    raise ValidationError("Workspace filters require a tile id")
                if resolver is not None:
                    resolved = resolver.resolve_for_tile(path, str(tile_id))
                    if resolved is None:
                        continue
                    path = resolved[1].field_path
                elif path.startswith(f"tile_{tile_id}:"):
                    path = path.split(":", 1)[1]
                elif path.startswith("tile_"):
                    continue
                else:
                    raise ValidationError("Shared filters require a workspace resolver")
            conditions.append(condition.model_copy(update={"field_path": path}))
        if conditions or not group.conditions:
            groups.append(Filter(connector=group.connector, conditions=conditions))
    return groups
