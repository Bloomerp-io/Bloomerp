from typing import Optional, Type

from django.apps import apps
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.db.models import BooleanField, Case, IntegerField, Max, Model, Value, When
from django.db.models.query import QuerySet

from bloomerp.filters.definition import Filters
from bloomerp.models.access_control import row_policy
from bloomerp.models.access_control.field_policy import FieldPolicy
from bloomerp.models.access_control.policy import Policy
from bloomerp.models.access_control.row_policy import RowPolicy
from bloomerp.models.access_control.row_policy_rule import RowPolicyRule
from bloomerp.models.application_field import ApplicationField
from bloomerp.models import BloomerpModel
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.compilers.django_q_permission_compiler import (
    CompiledDjangoAccess,
    DjangoQPermissionCompiler,
)
from bloomerp.permissions.compilers.python_permission_compiler import (
    PythonPermissionCompiler,
)
from bloomerp.permissions.compilers.sql_permission_compiler import (
    CompiledSqlAccess,
    SqlPermissionCompiler,
)
from bloomerp.permissions.definition import (
    AccessRule,
    BloomerpPermission,
    PermissionMatch,
    PermissionScope,
    RowPolicyRuleContent,
)
from bloomerp.utils.models import resolve_model_and_content_type


def resolve_permission_codenames(
    permissions: list[str] | list[BloomerpPermission] | str | BloomerpPermission
) -> list[str]:
    """
    Resolves a list of permission codenames from various input types.
    
    Input can be:
        - A list of permission codenames as strings. (e.g., "add_user", "change_user", "delete_user", "view_user")
        - A list of BloomerpPermission enums.
        - A list of strings refering to a codename (e.g., "add", "change", "delete", "view").
        - A single permission codename as a string.
        - A single BloomerpPermission enum.
        - A single string refering to a codename (e.g., "add", "change", "delete", "view").
    
    Args:
        permissions: A list of permission codenames, BloomerpPermission enums, or a single codename/enum.

    Returns:
        A list of permission codenames as strings. (e.g., ["add_user", "change_user", "delete_user", "view_user"])
    """
    if isinstance(permissions, (str, BloomerpPermission)):
        permissions = [permissions]

    if not isinstance(permissions, (list, tuple, set)):
        raise TypeError("permissions must be a permission or an iterable of permissions")

    codenames: list[str] = []
    for permission in permissions:
        if isinstance(permission, BloomerpPermission):
            codename = permission.value.codename
        elif isinstance(permission, str):
            codename = permission.strip()
            if "." in codename:
                codename = codename.rsplit(".", 1)[-1]
        else:
            raise TypeError("permissions must contain only strings or BloomerpPermission values")

        if not codename:
            raise ValueError("permission codenames cannot be empty")
        if codename not in codenames:
            codenames.append(codename)

    return codenames


def create_permission_str(obj_or_model: models.Model | Type[models.Model], permission: str) -> str:
    """Creates a permission string using an object or model.

    Args:
        obj_or_model (Model) : an object or model
        permission (str) : the permission
    """
    return f"{permission}_{obj_or_model._meta.model_name}"


def get_access_rules_from_model(model:Type[models.Model]) -> list[AccessRule]:
    """Returns specific access rules for a model.
        - Can be based on UserAccess
        - Can be based on public access

    Args:
        model (Type[models.Model]): The model for which to check certain access rules

    Returns:
        list[AccessRule]: list of access rules
    """
    # Public and model-level user access will be normalized to AccessRule here
    # when those legacy definitions are migrated. The user-policy manager must
    # not interpret those separate rule formats in the meantime.
    return []


class UserPolicyManager:
    policies: QuerySet[Policy]
    is_anonymous: bool

    def __init__(self, user: AbstractBloomerpUser | None):
        self.user = user
        self.is_anonymous = not user or user.is_anonymous
        self._policies: QuerySet[Policy] | None = None
        self.policies = self.get_user_policies()

    def get_user_policies(self) -> QuerySet[Policy]:
        """Retrieve all policies associated with the user.

        Returns:
            QuerySet[Policy]: queryset of policies linked to the user.
        """
        if self._policies is not None:
            return self._policies

        if self.is_anonymous:
            self._policies = Policy.objects.none()
            return self._policies

        self._policies = (
            Policy.objects.filter(
                models.Q(users=self.user) | models.Q(groups__in=self.user.groups.all())
            )
            .select_related(
                "row_policy",
                "field_policy",
                "field_policy__content_type",
            )
            .prefetch_related(
                "row_policy__rules__permissions",
                "global_permissions",
            )
            .distinct()
        )
        return self._policies

    def get_access_rules(
        self,
        model_or_content_type: Type[models.Model] | ContentType,
        permissions: list[str] | list[BloomerpPermission] | str | BloomerpPermission,
        match: PermissionMatch = PermissionMatch.ANY,
    ) -> list[AccessRule]:
        """Return compiler-ready access rules for a model and permissions.

        Args:
            model_or_content_type (Type[models.Model] | ContentType): The model for which to retrieve access rules.
            permissions (list[str] | list[BloomerpPermission] | str | BloomerpPermission): The requested permissions.
            match (PermissionMatch, optional): Whether all or any requested permissions must match. Defaults to PermissionMatch.ANY.

        Returns:
            list[AccessRule]: Access rules applicable to the model and requested permissions.
        """
        model, content_type = resolve_model_and_content_type(model_or_content_type)
        requested = PolicyManager._qualify_permission_codenames(model, permissions)
        access_rules: list[AccessRule] = []

        for policy in self.get_user_policies():
            if (
                not policy.row_policy_id
                or policy.row_policy.content_type_id != content_type.pk
            ):
                continue

            field_permissions = self._expanded_field_permissions(policy)
            for row_rule in policy.row_policy.rules.all():
                granted = {
                    permission.codename
                    for permission in row_rule.permissions.all()
                }
                if not self._permission_matches(granted, requested, match):
                    continue
                try:
                    row_content = RowPolicyRuleContent.model_validate(row_rule.rule)
                except Exception:
                    continue
                access_rules.append(
                    AccessRule(
                        row_permissions=[
                            row_content.model_copy(
                                update={"permissions": sorted(granted)}
                            )
                        ],
                        field_permissions=field_permissions,
                    )
                )

        access_rules.extend(get_access_rules_from_model(model))
        return access_rules

    def get_field_policies(self) -> QuerySet[FieldPolicy]:
        """Return field policies assigned directly or through a user group."""
        return FieldPolicy.objects.filter(
            policies__in=self.get_user_policies()
        ).distinct()

    def get_row_policies(self) -> QuerySet[RowPolicy]:
        """Return row policies assigned directly or through a user group."""
        return (
            RowPolicy.objects.filter(policies__in=self.get_user_policies())
            .prefetch_related("rules__permissions")
            .distinct()
        )

    @staticmethod
    def _permission_matches(
        granted: set[str],
        requested: list[str],
        match: PermissionMatch,
    ) -> bool:
        checks = [permission in granted for permission in requested]
        if not checks:
            return bool(granted)
        return all(checks) if match == PermissionMatch.ALL else any(checks)

    @staticmethod
    def _expanded_field_permissions(policy: Policy) -> dict[str, list[str]]:
        if not policy.field_policy_id or not isinstance(policy.field_policy.rule, dict):
            return {}

        expanded: dict[str, list[str]] = {}
        for field_id, permissions in policy.field_policy.rule.items():
            if field_id == "__all__":
                ids = ApplicationField.objects.filter(
                    content_type=policy.field_policy.content_type
                ).values_list("pk", flat=True)
                for application_field_id in ids:
                    key = str(application_field_id)
                    expanded[key] = list(
                        dict.fromkeys([*expanded.get(key, []), *(permissions or [])])
                    )
            else:
                key = str(field_id)
                expanded[key] = list(
                    dict.fromkeys([*expanded.get(key, []), *(permissions or [])])
                )
        return expanded

    @staticmethod
    def _field_queryset(content_type: ContentType) -> QuerySet[ApplicationField]:
        return ApplicationField.objects.filter(content_type=content_type).select_related(
            "content_type",
            "related_model",
        )

    def get_accessible_fields(
        self,
        model_or_content_type: Type[models.Model] | ContentType,
        permissions: Optional[list[str] | list[BloomerpPermission] | str | BloomerpPermission],
        match: PermissionMatch = PermissionMatch.ANY,
    ) -> QuerySet[ApplicationField]:
        model, content_type = resolve_model_and_content_type(model_or_content_type)
        fields = self._field_queryset(content_type)
        if getattr(self.user, "is_superuser", False):
            return fields
        if self.is_anonymous:
            return fields.none()

        requested = (
            PolicyManager._qualify_permission_codenames(model, permissions)
            if permissions is not None
            else []
        )
        if permissions is not None and not self.has_global_permission(
            content_type,
            permissions,
            match,
        ):
            return fields.none()

        allowed_ids: set[str] = set()
        field_policies = FieldPolicy.objects.filter(
            policies__in=self.get_user_policies(),
            content_type=content_type,
        ).distinct()
        for field_policy in field_policies:
            if not isinstance(field_policy.rule, dict):
                continue
            for field_id, permission_values in field_policy.rule.items():
                granted = set(permission_values or [])
                if not self._permission_matches(granted, requested, match):
                    continue
                if field_id == "__all__":
                    return fields
                allowed_ids.add(str(field_id))

        return fields.filter(pk__in=allowed_ids)

    def has_field_permission(
        self,
        field: ApplicationField,
        permissions: list[str] | list[BloomerpPermission] | str | BloomerpPermission,
        match: PermissionMatch = PermissionMatch.ANY,
    ) -> bool:
        """Checks whether a user has a field permission

        Args:
            field (ApplicationField): the application field
            permissions (list[str] | list[BloomerpPermission] | str | BloomerpPermission): the permissions
            match (PermissionMatch, optional): Whether to resolve for all or any permission. Defaults to PermissionMatch.ANY.

        Returns:
            bool
        """
        if not isinstance(field, ApplicationField):
            return False
        return self.get_accessible_fields(
            field.content_type,
            permissions,
            match,
        ).filter(pk=field.pk).exists()

    def get_accessible_content_types(
        self,
        permissions: list[str] | list[BloomerpPermission] | str | BloomerpPermission,
        match: PermissionMatch = PermissionMatch.ANY,
    ) -> QuerySet[ContentType]:
        """Returns a queryset of content types for which the user has access.

        Args:
            permissions (list[str] | list[BloomerpPermission] | str | BloomerpPermission): the permissions
            match (PermissionMatch, optional): Whether to resolve for all or any permission. Defaults to PermissionMatch.ANY.
        Returns:
            QuerySet[ContentType]: queryset of content types
        """
        if getattr(self.user, "is_superuser", False):
            return ContentType.objects.all()
        if self.is_anonymous:
            return ContentType.objects.none()

        candidate_models: dict[int, Type[models.Model]] = {}
        for policy in self.get_user_policies():
            if not policy.row_policy_id:
                continue
            model = policy.row_policy.content_type.model_class()
            if model is None:
                continue
            granted = {
                permission.codename
                for rule in policy.row_policy.rules.all()
                for permission in rule.permissions.all()
            }
            requested = PolicyManager._qualify_permission_codenames(
                model,
                permissions,
            )
            if not self._permission_matches(granted, requested, match):
                continue
            candidate_models[policy.row_policy.content_type_id] = model

        content_type_ids = {
            content_type_id
            for content_type_id, model in candidate_models.items()
            if self.has_global_permission(model, permissions, match)
        }

        return ContentType.objects.filter(pk__in=content_type_ids)
    
    def get_accessible_queryset(
        self,
        model_or_content_type: Type[models.Model] | ContentType,
        permissions: list[str] | list[BloomerpPermission] | str | BloomerpPermission,
        match: PermissionMatch = PermissionMatch.ANY,
    ) -> QuerySet[models.Model]:
        model, content_type = resolve_model_and_content_type(model_or_content_type)
        if getattr(self.user, "is_superuser", False):
            return model.objects.all()
        if self.is_anonymous:
            return model.objects.none()

        requested = PolicyManager._qualify_permission_codenames(model, permissions)
        access_rules = self.get_access_rules(model, permissions, match)
        return self.get_queryset_for_access_rules(
            model,
            access_rules,
            requested,
            match,
        )

    def get_queryset_for_access_rules(
        self,
        model_or_content_type: Type[models.Model] | ContentType,
        access_rules: list[AccessRule],
        permissions: list[str] | list[BloomerpPermission] | str | BloomerpPermission,
        match: PermissionMatch = PermissionMatch.ANY,
    ) -> QuerySet[models.Model]:
        """Apply supplied access rules for this manager's user.

        Unlike :meth:`get_accessible_queryset`, this method does not load the
        user's stored policies. It supports callers that need to evaluate a
        draft or model-configured set of access rules.
        """
        model, _ = resolve_model_and_content_type(model_or_content_type)
        compilation = self._compile_access_rules(
            model,
            access_rules,
            permissions,
            match,
        )
        return model.objects.filter(compilation.row_filter).distinct()

    def _compile_access_rules(
        self,
        model: Type[models.Model],
        access_rules: list[AccessRule],
        permissions: list[str] | list[BloomerpPermission] | str | BloomerpPermission,
        match: PermissionMatch,
    ) -> CompiledDjangoAccess:
        requested = PolicyManager._qualify_permission_codenames(model, permissions)
        return DjangoQPermissionCompiler(
            access_rules,
            user=self.user,
            model=model,
        ).compile(requested, match)

    def get_queryset(
        self,
        model_or_content_type: Type[models.Model] | ContentType,
        permissions: list[str] | list[BloomerpPermission] | str | BloomerpPermission,
        match: PermissionMatch = PermissionMatch.ANY,
    ) -> QuerySet[models.Model]:
        """Compatibility alias for the established permission-manager API."""
        return self.get_accessible_queryset(
            model_or_content_type,
            permissions,
            match,
        )

    def get_row_policy_rules(
        self,
        model_or_content_type: Type[models.Model] | ContentType,
        permissions: list[str] | list[BloomerpPermission] | str | BloomerpPermission,
        match: PermissionMatch = PermissionMatch.ANY,
    ) -> list[RowPolicyRule]:
        model, content_type = resolve_model_and_content_type(model_or_content_type)
        if getattr(self.user, "is_superuser", False) or self.is_anonymous:
            return []

        requested = PolicyManager._qualify_permission_codenames(model, permissions)
        applicable_rules: list[RowPolicyRule] = []
        for row_policy in self.get_row_policies().filter(content_type=content_type):
            for row_rule in row_policy.rules.all():
                granted = {
                    permission.codename
                    for permission in row_rule.permissions.all()
                }
                if self._permission_matches(granted, requested, match):
                    applicable_rules.append(row_rule)
        return applicable_rules

    def has_row_level_access(
        self,
        model_or_content_type: Type[models.Model] | ContentType,
        permissions: list[str] | list[BloomerpPermission] | str | BloomerpPermission,
        match: PermissionMatch = PermissionMatch.ANY,
    ) -> bool:
        """Whether the user user has any row level access

        Args:
            model_or_content_type (Type[models.Model] | ContentType): _description_
            permissions (list[str] | list[BloomerpPermission] | str | BloomerpPermission): _description_
            match (PermissionMatch, optional): _description_. Defaults to PermissionMatch.ANY.

        Returns:
            bool: _description_
        """
        if getattr(self.user, "is_superuser", False):
            return True
        return bool(
            self.get_row_policy_rules(
                model_or_content_type,
                permissions,
                match,
            )
        )

    def has_access_to_object(
        self,
        obj: models.Model,
        permissions: list[str] | list[BloomerpPermission] | str | BloomerpPermission,
        fields:Optional[list[str|ApplicationField]]=None,
        match: PermissionMatch = PermissionMatch.ANY,
        check_global: bool = True,
    ) -> bool:
        """Checks whether a user has access to a particular object.

        Args:
            obj (models.Model): the object
            permissions (list[str] | list[BloomerpPermission] | str | BloomerpPermission): the permissions
            match (PermissionMatch, optional): Match type. Defaults to PermissionMatch.ANY.
            check_global (bool, optional): Whether to check for global permissions first. Defaults to True.

        Returns:
            bool: The response
        """
        if not isinstance(obj, models.Model) or obj.pk is None:
            return False
        if check_global and not self.has_global_permission(type(obj), permissions, match):
            return False

        has_row_permission = self.get_accessible_queryset(
            type(obj),
            permissions,
            match,
        ).filter(pk=obj.pk).exists()

        if fields:

            accessible_fields = self.get_accessible_fields_for_object(obj, permissions, match)


        return has_row_permission

    def has_global_permission(
        self,
        model_or_content_type: Type[models.Model] | ContentType,
        permissions: list[str] | list[BloomerpPermission] | str | BloomerpPermission,
        match: PermissionMatch = PermissionMatch.ANY,
    ) -> bool:
        model, content_type = resolve_model_and_content_type(model_or_content_type)
        if getattr(self.user, "is_superuser", False):
            return True
        if self.is_anonymous:
            return False

        requested = PolicyManager._qualify_permission_codenames(model, permissions)
        policy_grants = {
            permission.codename
            for policy in self.get_user_policies()
            for permission in policy.global_permissions.all()
            if permission.content_type_id == content_type.pk
            and permission.codename in requested
        }
        checks = [
            self.user.has_perm(f"{content_type.app_label}.{codename}")
            or codename in policy_grants
            for codename in requested
        ]
        return all(checks) if match == PermissionMatch.ALL else any(checks)

    def get_accessible_fields_for_object(
        self,
        obj: models.Model,
        permissions: Optional[list[str] | list[BloomerpPermission] | str | BloomerpPermission],
        match: PermissionMatch = PermissionMatch.ANY,
    ) -> QuerySet[ApplicationField]:
        model, content_type = resolve_model_and_content_type(type(obj))
        fields = self._field_queryset(content_type)
        if obj.pk is None or self.is_anonymous:
            return fields.none()
        if getattr(self.user, "is_superuser", False):
            return fields
        if permissions is not None and not self.has_global_permission(
            model,
            permissions,
            match,
        ):
            return fields.none()

        requested = (
            PolicyManager._qualify_permission_codenames(model, permissions)
            if permissions is not None
            else []
        )
        access_rules = self.get_access_rules(model, permissions or [], match)
        compilation = DjangoQPermissionCompiler(
            access_rules,
            user=self.user,
            model=model,
        ).compile(requested, match)
        if not compilation.field_filters:
            return fields.none()

        annotations = {}
        fields_by_annotation: dict[str, list[ApplicationField]] = {}
        for index, (row_filter, allowed_fields) in enumerate(
            compilation.field_filters.items()
        ):
            alias = f"_bloomerp_access_rule_{index}"
            annotations[alias] = (
                Value(True, output_field=BooleanField())
                if not row_filter.children
                else Max(
                    Case(
                        When(row_filter, then=Value(1)),
                        default=Value(0),
                        output_field=IntegerField(),
                    )
                )
            )
            fields_by_annotation[alias] = allowed_fields

        match_values = (
            model.objects.filter(pk=obj.pk)
            .filter(compilation.row_filter)
            .annotate(**annotations)
            .values(*annotations)
            .first()
        )
        if match_values is None:
            return fields.none()

        allowed_ids = {
            field.pk
            for alias, allowed_fields in fields_by_annotation.items()
            if match_values[alias]
            for field in allowed_fields
        }
        return fields.filter(pk__in=allowed_ids)

    def get_accessible_models_and_fields(
        self, 
        permissions: list[str] | list[BloomerpPermission] | str | BloomerpPermission, 
        match: PermissionMatch = PermissionMatch.ANY
        ) -> dict[Type[models.Model], QuerySet[ApplicationField]]:
        """Returns a dictionary mapping models to their accessible fields for the user.

        Returns:
            dict[Type[models.Model], QuerySet[ApplicationField]]: A dictionary where keys are models and values are querysets of accessible fields.
        """
        if getattr(self.user, "is_superuser", False):
            return {
                model: ApplicationField.objects.filter(content_type=ContentType.objects.get_for_model(model))
                for model in apps.get_models()
            }
        
        
        
        tables_and_fields: dict[Type[models.Model], QuerySet[ApplicationField]] = {}
        row_policies = self.get_row_policies().select_related("content_type")

        for row_policy in row_policies:
            content_type = row_policy.content_type
            model: Type[models.Model] | None = content_type.model_class()
            if model is None:
                continue
            
            accessible_fields = self.get_accessible_fields(model, permissions=permissions, match=match)
            tables_and_fields[model] = accessible_fields

        return tables_and_fields
    
    def get_accessible_models(self, permissions: list[str] | list[BloomerpPermission] | str | BloomerpPermission, match: PermissionMatch = PermissionMatch.ANY) -> list[Type[models.Model]]:
        """Returns a list of models for which the user has access based on the provided permissions.

        Args:
            permissions (list[str] | list[BloomerpPermission] | str | BloomerpPermission): The permissions to check.
            match (PermissionMatch, optional): Whether all or any requested permissions must match. Defaults to PermissionMatch.ANY.
        """
        if getattr(self.user, "is_superuser", False):
            return list(apps.get_models())
        
        accessible_models: list[Type[models.Model]] = []
        row_policies = self.get_row_policies().select_related("content_type")
        for row_policy in row_policies:
            content_type = row_policy.content_type
            model: Type[models.Model] | None = content_type.model_class()
            if model is None:
                continue
            
            if self.has_global_permission(model, permissions=permissions, match=match):
                accessible_models.append(model)
                
        return accessible_models
        
    def validate_filters(self, model_or_content_type, filters: Filters) -> None:
        """Authorize filter dependencies without modifying filters or querysets.

        Until execution can constrain related rows, traversals require explicit
        unconditional related-row grants. Field access must cover every row
        that can influence the predicate; a union of field IDs is insufficient.
        """
        from django.core.exceptions import PermissionDenied
        from bloomerp.filters.resolver import FilterFieldResolver
        from bloomerp.permissions.compilers.base import BasePermissionCompiler

        model, _ = resolve_model_and_content_type(model_or_content_type)
        if self.is_anonymous or not self.has_global_permission(model, BloomerpPermission.VIEW):
            raise PermissionDenied("Model view permission is required for filtering")
        resolver = FilterFieldResolver.for_model(model)
        superuser = getattr(self.user, "is_superuser", False)
        grants_by_model = {}
        checked_fields = set()
        checked_relations = set()

        def grants(source_model):
            if source_model not in grants_by_model:
                if not self.has_global_permission(source_model, BloomerpPermission.VIEW):
                    raise PermissionDenied("Filtering references an inaccessible model")
                requested = PolicyManager._qualify_permission_codenames(source_model, BloomerpPermission.VIEW)
                grants_by_model[source_model] = [
                    (rule, row_rule)
                    for rule in self.get_access_rules(source_model, BloomerpPermission.VIEW)
                    for row_rule in rule.row_permissions
                    if BasePermissionCompiler.matches_requested_permissions(row_rule.permissions, requested, PermissionMatch.ANY)
                    and not (row_rule.connector == "OR" and not row_rule.conditions)
                ]
            return grants_by_model[source_model]

        def unconditional(row_rule):
            return row_rule.connector == "AND" and not row_rule.conditions

        def require_field(application_field, related):
            key = (application_field.pk, related)
            if key in checked_fields:
                return
            source_model = application_field.get_model()
            requested = PolicyManager._qualify_permission_codenames(source_model, BloomerpPermission.VIEW)
            coverage = []
            for rule, row_rule in grants(source_model):
                allowed = any(
                    BasePermissionCompiler.matches_requested_permissions(
                        rule.field_permissions.get(key, []), requested, PermissionMatch.ANY,
                    )
                    for key in (str(application_field.pk), application_field.field, "__all__")
                )
                if allowed and unconditional(row_rule):
                    checked_fields.add(key)
                    return
                coverage.append(allowed)
            if related or not coverage or not all(coverage):
                raise PermissionDenied("Filtering requires field access across all rows that can influence the result")
            checked_fields.add(key)

        for group in filters:
            for condition in group.conditions:
                traversed_relation = False
                for dependency in resolver.resolve_dependencies(condition.field_path):
                    if superuser:
                        continue
                    application_field = dependency.context.application_field
                    if application_field is None:
                        raise PermissionDenied("Filter field dependencies cannot be authorized")
                    require_field(application_field, related=traversed_relation)
                    related_model = getattr(application_field._get_model_field(), "related_model", None)
                    if related_model is not None:
                        traversed_relation = True
                    if related_model is not None and related_model not in checked_relations:
                        if not any(unconditional(row_rule) for _, row_rule in grants(related_model)):
                            raise PermissionDenied("Related-row filtering requires an unconditional view grant until scoped execution is supported")
                        checked_relations.add(related_model)

    def can_execute_filters(self, model_or_content_type, filters: Filters) -> bool:
        """Compatibility boolean wrapper; malformed filters still raise errors."""
        from django.core.exceptions import PermissionDenied
        try:
            self.validate_filters(model_or_content_type, filters)
        except PermissionDenied:
            return False
        return True

    def get_accessible_sql_query(
        self,
        sql: str,
        permissions: list[str] | list[BloomerpPermission] | str | BloomerpPermission = BloomerpPermission.VIEW,
        match: PermissionMatch = PermissionMatch.ANY,
    ) -> CompiledSqlAccess:
        """Compile user SQL against model, row, and field permissions."""
        if getattr(self.user, "is_superuser", False):
            return CompiledSqlAccess(query=sql)
        if self.is_anonymous:
            raise PermissionError("Anonymous users cannot execute SQL queries")

        rules: dict[Type[models.Model], list[AccessRule]] = {}
        for row_policy in self.get_row_policies().select_related("content_type"):
            model = row_policy.content_type.model_class()
            if model is None or model in rules:
                continue
            if not self.has_global_permission(model, permissions, match):
                continue
            rules[model] = self.get_access_rules(model, permissions, match)

        return SqlPermissionCompiler(rules, user=self.user).compile(
            sql,
            permissions,
            match,
        )

    def candidate_matches_row_policies(
        self,
        candidate: models.Model,
        permissions: list[str] | list[BloomerpPermission] | str | BloomerpPermission,
        match: PermissionMatch = PermissionMatch.ANY,
    ) -> bool:
        """Evaluate row rules against a complete, possibly unsaved candidate."""
        if not isinstance(candidate, models.Model):
            return False
        if getattr(self.user, "is_superuser", False):
            return True
        if self.is_anonymous:
            return False

        requested = PolicyManager._qualify_permission_codenames(type(candidate), permissions)
        rules = self.get_access_rules(
            type(candidate),
            permissions,
            match,
        )
        evaluator = PythonPermissionCompiler(
            rules,
            user=self.user,
            model=type(candidate),
        ).compile(
            requested,
            match,
        )
        return evaluator.matches(candidate)

    

class PolicyManager:
    @staticmethod
    def _qualify_permission_codenames(
        model: Type[models.Model],
        permissions: list[str] | list[BloomerpPermission] | str | BloomerpPermission,
        *,
        required_scope: PermissionScope | None = None,
    ) -> list[str]:
        values = permissions if isinstance(permissions, (list, tuple, set)) else [permissions]
        for permission in values:
            if (
                required_scope is not None
                and isinstance(permission, BloomerpPermission)
                and required_scope not in permission.value.scopes
            ):
                raise ValueError(
                    f"Permission '{permission.value.codename}' does not support "
                    f"the '{required_scope.value}' scope"
                )

        model_suffix = f"_{model._meta.model_name}"
        qualified: list[str] = []
        for codename in resolve_permission_codenames(permissions):
            if not codename.endswith(model_suffix):
                codename = create_permission_str(model, codename)
            if codename not in qualified:
                qualified.append(codename)
        return qualified

    @staticmethod
    def _get_permissions(
        content_type: ContentType,
        codenames: list[str],
    ) -> list[Permission]:
        permissions_by_codename = {
            permission.codename: permission
            for permission in Permission.objects.filter(
                content_type=content_type,
                codename__in=codenames,
            )
        }
        missing = [codename for codename in codenames if codename not in permissions_by_codename]
        if missing:
            raise ValueError(
                "Unknown permissions for "
                f"'{content_type.app_label}.{content_type.model}': {', '.join(missing)}"
            )
        return [permissions_by_codename[codename] for codename in codenames]

    @staticmethod
    def _normalize_row_rule(
        content_type: ContentType,
        rule: RowPolicyRuleContent,
    ) -> dict:
        if not isinstance(rule, RowPolicyRuleContent):
            rule = RowPolicyRuleContent.model_validate(rule)

        if rule._legacy_content_type_ids - {content_type.pk}:
            raise ValueError("Field belongs to a different content type")
        from django.core.exceptions import ValidationError as DjangoValidationError
        from bloomerp.filters.resolver import FilterFieldResolver, resolve_lookup
        resolver = FilterFieldResolver.for_model(content_type.model_class())
        for condition in rule.conditions:
            try:
                field, target = resolver.resolve(condition.field_path)
            except DjangoValidationError as exc:
                raise ValueError(f"Unknown field '{condition.field_path}'") from exc
            lookup = resolve_lookup(field, target, condition.lookup_id)
            if lookup.nested:
                raise ValueError("A row condition requires a terminal lookup")
        return rule.model_dump(exclude={"permissions"}, exclude_none=True)

    @classmethod
    @transaction.atomic
    def _create_policy(
        cls,
        model_or_content_type: Type[models.Model] | models.Model | ContentType,
        field_permissions: dict[
            str | ApplicationField,
            list[str] | list[BloomerpPermission] | str | BloomerpPermission,
        ],
        row_permissions: list[RowPolicyRuleContent],
        global_permissions: Optional[list[str] | list[BloomerpPermission] | str | BloomerpPermission] = None,
    ) -> Policy:
        """Provides a simple interface to create a particular policy

        Args:
            model_or_content_type (Type[models.Model] | ContentType): The model or content type for which to create a policy
            field_permissions (dict[str, list[str]  |  list[BloomerpPermission]]): The field permissions
            row_permissions (list[RowPolicyRuleContent]): The row permissions
            global_permissions (Optional[list[str]  |  list[BloomerpPermission]  |  str  |  BloomerpPermission], optional): Optional global permissions. Defaults to None.
                Note: if global_permissions are None, it will infer the global permissions from the field permissions and row permissions.

        Returns:
            Policy: The created policy instance
        """
        
        model, content_type = resolve_model_and_content_type(model_or_content_type)
        if not isinstance(field_permissions, dict):
            raise TypeError("field_permissions must be a dictionary")
        if not isinstance(row_permissions, (list, tuple)):
            raise TypeError("row_permissions must be a list of row policy rules")

        field_rule: dict[str, list[str]] = {}
        inferred_codenames: list[str] = []
        for field, permissions in field_permissions.items():
            if field == "__all__":
                field_id = "__all__"
            else:
                application_field = ApplicationField.resolve_for_content_type(
                    content_type,
                    field,
                )
                field_id = str(application_field.pk)
            field_codenames = cls._qualify_permission_codenames(
                model,
                permissions,
                required_scope=PermissionScope.FIELD,
            )
            if not field_codenames:
                raise ValueError(f"At least one permission is required for field '{field}'")
            field_rule[field_id] = field_codenames
            for codename in field_codenames:
                if codename not in inferred_codenames:
                    inferred_codenames.append(codename)

        normalized_row_rules: list[tuple[RowPolicyRuleContent, list[str]]] = []
        for row_rule in row_permissions:
            if not isinstance(row_rule, RowPolicyRuleContent):
                row_rule = RowPolicyRuleContent.model_validate(row_rule)
            row_codenames = cls._qualify_permission_codenames(
                model,
                row_rule.permissions,
                required_scope=PermissionScope.ROW,
            )
            if not row_codenames:
                raise ValueError("Each row policy rule requires at least one permission")
            normalized_row_rules.append((row_rule, row_codenames))
            for codename in row_codenames:
                if codename not in inferred_codenames:
                    inferred_codenames.append(codename)

        if global_permissions is None:
            global_codenames = inferred_codenames
        else:
            global_codenames = cls._qualify_permission_codenames(
                model,
                global_permissions,
                required_scope=PermissionScope.GLOBAL,
            )
            missing_global_grants = [
                codename for codename in inferred_codenames if codename not in global_codenames
            ]
            if missing_global_grants:
                raise ValueError(
                    "Row and field permissions must also be global permissions: "
                    + ", ".join(missing_global_grants)
                )

        permission_objects = cls._get_permissions(content_type, global_codenames)
        model_label = str(model._meta.verbose_name).title()
        row_policy = RowPolicy.objects.create(
            content_type=content_type,
            name=f"{model_label} row policy",
        )
        for row_rule, row_codenames in normalized_row_rules:
            rule = RowPolicyRule.objects.create(
                row_policy=row_policy,
                rule=cls._normalize_row_rule(content_type, row_rule),
            )
            rule.permissions.set(cls._get_permissions(content_type, row_codenames))

        field_policy = FieldPolicy.objects.create(
            content_type=content_type,
            name=f"{model_label} field policy",
            rule=field_rule,
        )
        policy = Policy.objects.create(
            name=f"{model_label} policy",
            row_policy=row_policy,
            field_policy=field_policy,
        )
        policy.global_permissions.set(permission_objects)
        return policy
    
    @classmethod
    @transaction.atomic
    def create_policy(
        cls,
        model_or_content_type: Type[models.Model] | models.Model | ContentType,
        access_rule: AccessRule | None = None,
        global_permissions: Optional[list[str] | list[BloomerpPermission] | str | BloomerpPermission] = None,
        *,
        rule: AccessRule | None = None,
        field_permissions: Optional[
            dict[
                str | ApplicationField,
                list[str] | list[BloomerpPermission] | str | BloomerpPermission,
            ]
        ] = None,
        row_permissions: Optional[list[RowPolicyRuleContent]] = None,
    ) -> Policy:
        """Provides a simple interface to create a particular policy

        Args:
            model_or_content_type (Type[models.Model] | ContentType): The model or content type for which to create a policy
            field_permissions (dict[str, list[str]  |  list[BloomerpPermission]]): The field permissions
            row_permissions (list[RowPolicyRuleContent]): The row permissions
            global_permissions (Optional[list[str]  |  list[BloomerpPermission]  |  str  |  BloomerpPermission], optional): Optional global permissions. Defaults to None.
                Note: if global_permissions are None, it will infer the global permissions from the field permissions and row permissions.

        Returns:
            Policy: The created policy instance
        """
        selected_rule = rule or access_rule
        if rule is not None and access_rule is not None:
            raise TypeError("Pass either access_rule or rule, not both")
        if selected_rule is not None:
            if field_permissions is not None or row_permissions is not None:
                raise TypeError(
                    "AccessRule cannot be combined with field_permissions or "
                    "row_permissions"
                )
            field_permissions = selected_rule.field_permissions
            row_permissions = selected_rule.row_permissions

        if field_permissions is None or row_permissions is None:
            raise TypeError(
                "Pass an AccessRule or both field_permissions and row_permissions"
            )

        return cls._create_policy(
            model_or_content_type,
            field_permissions=field_permissions,
            row_permissions=row_permissions,
            global_permissions=global_permissions,
        )
    
    
    @staticmethod
    def assign(
        policy: Policy,
        user_or_group: AbstractBloomerpUser | Group
    ) -> None:
        """Provides a simple interface to assign certain users or groups to a policy

        Args:
            policy (Policy): the policy
            user_or_group (AbstractBloomerpUser | Group): The user or group object
        """
        if not isinstance(policy, Policy):
            raise TypeError("policy must be a Policy instance")
        if isinstance(user_or_group, Group):
            policy.assign_group(user_or_group)
        elif isinstance(user_or_group, AbstractBloomerpUser):
            policy.assign_user(user_or_group)
        else:
            raise TypeError("user_or_group must be an AbstractBloomerpUser or Group instance")
    
    @staticmethod
    def users_assigned_to_policy(
        policy: Policy
    ) -> QuerySet[AbstractBloomerpUser]:
        """Provides a simple interface to get all users assigned to a particular policy. This includes users assigned directly to the policy and users assigned to groups that are assigned to the policy.

        Args:
            policy (Policy): The policy

        Returns:
            QuerySet[AbstractBloomerpUser]: The users assigned to the policy
        """
        if not isinstance(policy, Policy):
            raise TypeError("policy must be a Policy instance")
        return policy.get_users()


def get_bloomerp_model_default_permissions(model: type[models.Model]) -> tuple[str, ...]:
    """Returns the default permissions for a model

    Args:
        model (type[models.Model]): the model

    Returns:
        tuple[str, ...]: the default permissions for the model
    """
    default_permissions = tuple(getattr(model._meta, "default_permissions", ()))
    if issubclass(model, BloomerpModel):
        return tuple(dict.fromkeys((*default_permissions, *BloomerpPermission.to_tuple())))
    return default_permissions


def ensure_model_permissions(model: type[models.Model]) -> int:
    """Ensures permissions the default permissions are created for models

    Args:
        model (type[models.Model]): the model

    Returns:
        int: the number of permissions created
    """
    if model._meta.abstract or model._meta.proxy:
        return 0

    default_permissions = get_bloomerp_model_default_permissions(model)
    if not default_permissions:
        return 0

    content_type = ContentType.objects.get_for_model(model)
    created_count = 0

    for permission in default_permissions:
        _, created = Permission.objects.get_or_create(
            codename=f"{permission}_{model._meta.model_name}",
            content_type=content_type,
            defaults={"name": f"Can {permission} {model._meta.verbose_name}"},
        )
        if created:
            created_count += 1

    return created_count


def ensure_bloomerp_model_permissions(**kwargs) -> int:
    """Ensures permissions for all Bloomerp models.

    Returns:
        int: the number of permissions created
    """
    created_count = 0
    for model in apps.get_models():
        created_count += ensure_model_permissions(model)
    return created_count
    
    
