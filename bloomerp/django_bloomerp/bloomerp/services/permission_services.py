"""
This module provides services related to permissions management.
Classes:
    BasePermissions (Enum): Defines basic permission types such as READ, WRITE, DELETE, and UPDATE.
Functions:
    has_object_permission(user: User, permission: BasePermission) -> bool:
        Checks if the given user has the specified object-level permission.
"""

"""Services regarding permissions"""
import logging
from django.db import models
from django.db.models import Model
from bloomerp.models.users.user import AbstractBloomerpUser, User
from enum import Enum
from django.db.models.query import QuerySet
from enum import Enum
from bloomerp.models import ApplicationField
from django.db.models import QuerySet
from bloomerp.models.access_control import Policy
from bloomerp.models.access_control.field_policy import FieldPolicy
from bloomerp.models.access_control.row_policy import RowPolicy
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import Permission
from typing import Literal, Type
from django.db.models import Q
from bloomerp.field_types import Lookup
from django.core.exceptions import FieldDoesNotExist
from time import perf_counter
from django.utils import timezone

logger = logging.getLogger(__name__)
    
# --------------------------
# Service Functions
# --------------------------
def create_permission_str(obj_or_model: Model, permission: str) -> str:
    """Creates a permission string using an object or model.

    Args:
        obj_or_model (Model) : an object or model
        permission (str) : the permission
    """
    return f"{permission}_{obj_or_model._meta.model_name}"
    

class UserPermissionManager:
    policies : QuerySet[Policy]
    
    def __init__(self, user: AbstractBloomerpUser, trace_label: str | None = None):
        self.user = user
        self.is_anonymous = not user or user.is_anonymous
        self.trace_label = trace_label or f"user_id={getattr(user, 'pk', 'anonymous')}"
        
        self.policies = self.get_user_policies()

    def _log_timing(self, phase: str, started_at: float, **details):
        elapsed_ms = (perf_counter() - started_at) * 1000
        detail_str = " ".join(f"{key}={value}" for key, value in details.items() if value is not None)
        suffix = f" {detail_str}" if detail_str else ""
        logger.info(
            "api_timing ts=%s %s component=permission_manager phase=%s elapsed_ms=%.2f%s",
            timezone.now().isoformat(),
            self.trace_label,
            phase,
            elapsed_ms,
            suffix,
        )
    
    def get_user_policies(self) -> QuerySet[Policy]:
        """Retrieve all policies associated with the user.

        Returns:
            QuerySet[Policy]: queryset of policies linked to the user.
        """
        timer = perf_counter()
        if self.is_anonymous:
            self._log_timing("get_user_policies", timer, policy_count=0, anonymous=True)
            return Policy.objects.none()

        queryset = (
            Policy.objects.filter(
                models.Q(users=self.user) | models.Q(groups__in=self.user.groups.all())
            )
            .distinct()
        )
        self._log_timing("get_user_policies", timer)
        return queryset
        
    def get_field_policies(self) -> QuerySet[FieldPolicy]:
        """Retrieve field policies associated with the user.
        
        Returns:
            QuerySet[FieldPolicy]: queryset of field policies linked to the user.
        """
        timer = perf_counter()
        queryset = FieldPolicy.objects.filter(
            policies__in=self.policies
        ).distinct()
        self._log_timing("get_field_policies", timer)
        return queryset
    
    def get_row_policies(self) -> QuerySet[RowPolicy]:
        """Retrieve row policies associated with the user.

        Returns:
            QuerySet[RowPolicy]: queryset of row policies linked to the user.
        """
        timer = perf_counter()
        queryset = (
            RowPolicy.objects.filter(
                policies__in=self.policies
            )
            .prefetch_related("rules__permissions")
            .distinct()
        )
        self._log_timing("get_row_policies", timer)
        return queryset

    def _resolve_lookup(self, application_field: ApplicationField, operator_str: str) -> Lookup | None:
        if not application_field or not operator_str:
            return None

        field_type = application_field.get_field_type_enum()
        lookup_enum = field_type.get_lookup_by_id(operator_str)
        if lookup_enum:
            return lookup_enum

        for lookup in field_type.lookups:
            if lookup.value.django_representation == operator_str:
                return lookup
            if operator_str in (lookup.value.aliases or []):
                return lookup

        return None

    def _normalize_lookup_value(self, lookup: str, value):
        normalized_lookup = str(lookup or "").strip().lower()

        if normalized_lookup == "in" and isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]

        if normalized_lookup == "isnull":
            if isinstance(value, str):
                return value.lower() in {"true", "1", "yes"}
            return bool(value)

        return value

    def build_q_for_rule_dict(self, rule_dict: dict) -> Q | None:
        if not isinstance(rule_dict, dict):
            return None

        application_field_id = rule_dict.get("application_field_id")
        operator_id = rule_dict.get("operator")
        value = rule_dict.get("value")
        field_path = rule_dict.get("field")

        if field_path == "__all__" or application_field_id == "__all__":
            return Q()

        if not application_field_id or not operator_id:
            return None

        application_field = ApplicationField.objects.filter(id=application_field_id).first()
        if not application_field:
            return None

        operator_str = str(operator_id)
        field_name = application_field.field
        if isinstance(field_path, str) and "__" in field_path:
            field_name = field_path

        if operator_str.startswith("__"):
            filter_key = operator_str.lstrip("_")
            advanced_lookup = filter_key.rsplit("__", 1)[-1] if "__" in filter_key else ""
            return Q(**{filter_key: self._normalize_lookup_value(advanced_lookup, value)})

        lookup_enum = self._resolve_lookup(application_field, operator_str)
        django_lookup = (lookup_enum.value.django_representation or "").strip() if lookup_enum else operator_str

        if lookup_enum == Lookup.EQUALS_USER or str(value) == "$user":
            return Q(**{field_name: self.user})

        if lookup_enum == Lookup.NOT_EQUALS:
            return ~Q(**{field_name: value})

        filter_key = f"{field_name}__{django_lookup}" if django_lookup else field_name
        return Q(**{filter_key: self._normalize_lookup_value(django_lookup, value)})

    def build_queryset_from_rule_dicts(
        self,
        model_or_content_type: Type[models.Model] | ContentType,
        rule_dicts: list[dict],
    ) -> QuerySet[models.Model]:
        # TODO: Get this out of the permissin manager
        if isinstance(model_or_content_type, ContentType):
            content_type = model_or_content_type
            model = content_type.model_class()
        elif issubclass(model_or_content_type, models.Model):
            model = model_or_content_type
            content_type = ContentType.objects.get_for_model(model)
        else:
            raise TypeError("model_or_content_type must be a Django model class or a ContentType")

        if model is None:
            return models.QuerySet(model=None).none()

        combined_q = Q()
        has_any_rule = False

        for rule_dict in rule_dicts:
            try:
                rule_q = self.build_q_for_rule_dict(rule_dict)
            except Exception:
                rule_q = None

            if rule_q is None:
                continue

            combined_q |= rule_q
            has_any_rule = True

        if not has_any_rule:
            return model.objects.none()

        return model.objects.filter(combined_q).distinct()
    
    def has_global_permission(self, model_or_content_type : models.Model | ContentType, permission_str: str) -> bool:
        """Return whether the user has the given model-level permission.

        This checks both Django's legacy permission system and any matching
        permissions granted through assigned Policy.global_permissions.

        Args:
            model_or_content_type: A Django model class, model instance, or
                ContentType identifying the protected model.
            permission_str: The full permission codename to check, such as
                ``add_customer`` or ``view_invoice``.

        Returns:
            bool: True when the user has the requested global permission.

        Raises:
            TypeError: If ``model_or_content_type`` is not a model, model
                class, or ContentType.
        """
        timer = perf_counter()
        if self.is_anonymous:
            self._log_timing("has_global_permission", timer, allowed=False, anonymous=True)
            return False

        if getattr(self.user, "is_superuser", False):
            self._log_timing("has_global_permission", timer, allowed=True, superuser=True)
            return True

        if isinstance(model_or_content_type, ContentType):
            content_type = model_or_content_type
            model_class = content_type.model_class()
        elif isinstance(model_or_content_type, models.Model):
            content_type = ContentType.objects.get_for_model(model_or_content_type)
        elif isinstance(model_or_content_type, type) and issubclass(model_or_content_type, models.Model):
            content_type = ContentType.objects.get_for_model(model_or_content_type)
        else:
            raise TypeError("model_or_content_type must be a Django model class, instance, or ContentType")

        permission_value = str(permission_str or "").strip()
        if not permission_value:
            self._log_timing("has_global_permission", timer, allowed=False, empty_permission=True)
            return False

        if "." in permission_value and self.user.has_perm(permission_value):
            self._log_timing("has_global_permission", timer, allowed=True, source="django_qualified")
            return True

        permission_codename = permission_value.split(".", 1)[-1]

        if self.user.has_perm(f"{content_type.app_label}.{permission_codename}"):
            self._log_timing("has_global_permission", timer, allowed=True, source="django_content_type")
            return True

        allowed = self.policies.filter(
            global_permissions__content_type=content_type,
            global_permissions__codename=permission_codename,
        ).exists()
        self._log_timing("has_global_permission", timer, allowed=allowed, source="policy")
        return allowed

    def get_row_policy_rules(self, model_or_content_type: Type[models.Model] | ContentType, permission_str: str):
        # TODO: Add method description
        timer = perf_counter()
        if isinstance(model_or_content_type, ContentType):
            content_type = model_or_content_type
        elif issubclass(model_or_content_type, models.Model):
            content_type = ContentType.objects.get_for_model(model_or_content_type)
        else:
            raise TypeError("model_or_content_type must be a Django model class or a ContentType")

        if getattr(self.user, "is_superuser", False):
            self._log_timing("get_row_policy_rules", timer, rule_count=0, superuser=True)
            return []

        applicable_rules = []
        for row_policy in self.get_row_policies().filter(content_type=content_type):
            for rule_obj in row_policy.rules.all():
                perms = getattr(rule_obj, "permissions", None)
                if perms is None:
                    continue
                if permission_str in {p.codename for p in perms.all()}:
                    applicable_rules.append(rule_obj)
        self._log_timing("get_row_policy_rules", timer, rule_count=len(applicable_rules), permission=permission_str)
        return applicable_rules

    def has_row_level_access(self, model_or_content_type: Type[models.Model] | ContentType, permission_str: str) -> bool:
        # TODO: Add method description
        if getattr(self.user, "is_superuser", False):
            return True
        return len(self.get_row_policy_rules(model_or_content_type, permission_str)) > 0

    def candidate_matches_row_policies(
        self,
        model_or_content_type: Type[models.Model] | ContentType,
        permission_str: str,
        cleaned_data: dict,
    ) -> bool:
        # TODO: Add method description, is a bit of a vague api right now
        if isinstance(model_or_content_type, ContentType):
            content_type = model_or_content_type
            model = content_type.model_class()
        elif issubclass(model_or_content_type, models.Model):
            model = model_or_content_type
            content_type = ContentType.objects.get_for_model(model)
        else:
            raise TypeError("model_or_content_type must be a Django model class or a ContentType")

        if model is None:
            return False

        if getattr(self.user, "is_superuser", False):
            return True

        rules = self.get_row_policy_rules(content_type, permission_str)
        if not rules:
            return False

        candidate = model(**cleaned_data)
        if hasattr(candidate, "created_by") and not getattr(candidate, "created_by", None):
            candidate.created_by = self.user
        if hasattr(candidate, "updated_by") and not getattr(candidate, "updated_by", None):
            candidate.updated_by = self.user

        for rule in rules:
            if self._candidate_matches_rule(candidate, rule):
                return True
        return False
    
    def has_field_permission(self, field: ApplicationField, permission_str:str) -> bool:
        """Check whether the user has the given permission for a specific field.

        Args:
            field (ApplicationField): the application field to check
            permission_str (str): the permission string to check for

        Returns:
            bool: True if the user has the permission on the field, False otherwise
        """
        timer = perf_counter()
        if not field:
            self._log_timing("has_field_permission", timer, allowed=False, missing_field=True)
            return False

        # Superusers always have field access
        if getattr(self.user, "is_superuser", False):
            self._log_timing("has_field_permission", timer, allowed=True, superuser=True, field_id=field.id)
            return True

        permission_value = str(permission_str)

        policies = self.get_field_policies().filter(content_type=field.content_type)
        if not policies.exists():
            self._log_timing("has_field_permission", timer, allowed=False, field_id=field.id, permission=permission_str)
            return False

        for policy in policies:
            rules = policy.rule or {}
            if not isinstance(rules, dict):
                continue

            # Check __all__ wildcard
            wildcard_perms = rules.get("__all__")
            if isinstance(wildcard_perms, list) and permission_value in wildcard_perms:
                return True

            # Check for explicit field id match. Keys may be strings or ints.
            for field_id, permissions in rules.items():
                if field_id == "__all__":
                    continue
                if not isinstance(permissions, list):
                    continue

                try:
                    if str(field_id) == str(field.id) and permission_value in permissions:
                        self._log_timing("has_field_permission", timer, allowed=True, field_id=field.id, permission=permission_str)
                        return True
                except Exception:
                    # Defensive: skip malformed keys
                    continue

        self._log_timing("has_field_permission", timer, allowed=False, field_id=field.id, permission=permission_str)
        return False
    
    def get_accessible_fields(self, model_or_content_type: models.Model | ContentType, permission_str:str) -> QuerySet[ApplicationField]:
        """Returns the application fields with a certain permission.

        Args:
            model_or_content_type (models.Model | ContentType): The model or content type to check fields for.
            permission_str (str): The permission string to check.

        Returns:
            QuerySet[ApplicationField]: Queryset of application fields with the specified permission.
        """
        timer = perf_counter()
        if not model_or_content_type:
            self._log_timing("get_accessible_fields", timer, field_count=0, missing_content_type=True)
            return ApplicationField.objects.none()

        if isinstance(model_or_content_type, ContentType):
            content_type = model_or_content_type
        elif isinstance(model_or_content_type, models.Model):
            content_type = ContentType.objects.get_for_model(model_or_content_type)
        else:
            content_type = model_or_content_type
        
        # Return all fields if user is superuser
        if self.user.is_superuser:
            queryset = ApplicationField.objects.filter(content_type=content_type)
            self._log_timing("get_accessible_fields", timer, field_count="all", superuser=True)
            return queryset
        
        permission_value = str(permission_str)

        policies = self.get_field_policies().filter(content_type=content_type)
        
        if not policies.exists():
            self._log_timing("get_accessible_fields", timer, field_count=0, permission=permission_str)
            return ApplicationField.objects.none()

        allowed_field_ids: set[str] = set()

        for policy in policies:
            rules = policy.rule or {}
            if not isinstance(rules, dict):
                continue

            for field_id, permissions in rules.items():
                if not isinstance(permissions, list):
                    continue
                if permission_value not in permissions:
                    continue

                if field_id == "__all__":
                    queryset = ApplicationField.objects.filter(content_type=content_type)
                    self._log_timing("get_accessible_fields", timer, field_count="all", permission=permission_str)
                    return queryset

                allowed_field_ids.add(str(field_id))

        if not allowed_field_ids:
            self._log_timing("get_accessible_fields", timer, field_count=0, permission=permission_str)
            return ApplicationField.objects.none()

        queryset = ApplicationField.objects.filter(
            content_type=content_type,
            id__in=allowed_field_ids
        )
        self._log_timing("get_accessible_fields", timer, field_count=len(allowed_field_ids), permission=permission_str)
        return queryset
        
    def has_access_to_object(self, object:models.Model, permission_str:str, check_global:bool=True) -> bool:
        """Returns a boolean that checks whether a user has access to a particular object

        Args:
            object (models.Model): the django ORM object
            permission_str (str): the permission to check
            check_global (bool): whether to check the global permission for the object as well. Defaults to true.

        Returns:
            bool: whether the user has access to the object
        """
        normalized_permission = str(permission_str or "").strip()
        if normalized_permission and "_" not in normalized_permission and "." not in normalized_permission:
            normalized_permission = create_permission_str(object, normalized_permission)

        if check_global:
            has_global_permission = self.has_global_permission(
                object._meta.model,
                normalized_permission
            )
        else:
            has_global_permission = True

        has_obj_permission = self.get_queryset(object._meta.model, normalized_permission).filter(
                    id=object.id
                ).exists()

        return (has_global_permission and has_obj_permission)
    
    def get_queryset(self, model_or_content_type:Type[models.Model]|ContentType, permission_str:str) -> QuerySet[models.Model]:
        """Returns the queryset for a particular model that the user has access to

        Args:
            model_or_content_type (models.Model | ContentType): the model or 

        Returns:
            QuerySet[models.Model]: _description_
        """
        timer = perf_counter()
        if isinstance(model_or_content_type, ContentType):
            content_type = model_or_content_type
            model = content_type.model_class()
        elif issubclass(model_or_content_type, models.Model):
            model = model_or_content_type
            content_type = ContentType.objects.get_for_model(model)
        else:
            raise TypeError("model_or_content_type must be a Django model class or a ContentType")

        if model is None:
            self._log_timing("get_queryset", timer, permission=permission_str, result="none_model")
            return models.QuerySet(model=None).none()  # defensive; should not happen

        if not self.user:
            self._log_timing("get_queryset", timer, permission=permission_str, result="no_user")
            return model.objects.none()

        # Superusers always see the full queryset
        if getattr(self.user, "is_superuser", False):
            queryset = model.objects.all()
            self._log_timing("get_queryset", timer, permission=permission_str, result="superuser")
            return queryset

        permission_value = str(permission_str)

        # Find row policies applicable to this content type
        row_policies = self.get_row_policies().filter(content_type=content_type)
        if not row_policies.exists():
            self._log_timing("get_queryset", timer, permission=permission_str, rule_count=0, result="no_row_policies")
            return model.objects.none()

        applicable_rule_dicts: list[dict] = []

        for row_policy in row_policies:
            for rule_obj in row_policy.rules.all():
                # Only consider rules that grant the requested permission
                perms = getattr(rule_obj, "permissions", None)
                if perms is None:
                    continue

                if permission_value not in {p.codename for p in perms.all()}:
                    continue

                rule_dict = getattr(rule_obj, "rule", None) or {}
                if isinstance(rule_dict, dict):
                    applicable_rule_dicts.append(rule_dict)

        queryset = self.build_queryset_from_rule_dicts(content_type, applicable_rule_dicts)
        self._log_timing("get_queryset", timer, permission=permission_str, rule_count=len(applicable_rule_dicts), result="filtered")
        return queryset

    def candidate_matches_rule_dict(self, candidate: models.Model, rule_dict: dict) -> bool:
        if not isinstance(rule_dict, dict):
            return False

        application_field_id = rule_dict.get("application_field_id")
        operator_id = rule_dict.get("operator")
        expected_value = rule_dict.get("value")
        explicit_field_path = rule_dict.get("field")

        if explicit_field_path == "__all__" or application_field_id == "__all__":
            return True

        if not application_field_id or not operator_id:
            return False

        application_field = ApplicationField.objects.filter(id=application_field_id).first()
        if not application_field:
            return False

        field_path = application_field.field
        operator_str = str(operator_id)
        if isinstance(explicit_field_path, str) and "__" in explicit_field_path:
            field_path = explicit_field_path

        resolved_value = self._resolve_candidate_value(candidate, field_path)

        lookup_enum = None
        if operator_str.startswith("__"):
            field_path = operator_str.lstrip("_")
            resolved_value = self._resolve_candidate_value(candidate, field_path)
            lookup = "exact"
        else:
            try:
                lookup_enum = application_field.get_field_type_enum().get_lookup_by_id(operator_str)
            except Exception:
                lookup_enum = None
            if not lookup_enum:
                for lookup in application_field.get_field_type_enum().lookups:
                    if operator_str == lookup.value.django_representation or operator_str in (lookup.value.aliases or []):
                        lookup_enum = lookup
                        break
            lookup = lookup_enum.value.django_representation if lookup_enum else operator_str

        if lookup_enum == Lookup.EQUALS_USER or str(expected_value) == "$user":
            return self._normalize_compare_value(resolved_value) == self._normalize_compare_value(self.user)


        if operator_str.startswith("__"):
            return self._matches_lookup(resolved_value, expected_value, lookup)

        return self._matches_lookup(resolved_value, expected_value, lookup)

    def _candidate_matches_rule(self, candidate: models.Model, rule_obj) -> bool:
        # TODO: Add method description
        rule_dict = getattr(rule_obj, "rule", None) or {}
        return self.candidate_matches_rule_dict(candidate, rule_dict)

    def _resolve_candidate_value(self, candidate: models.Model, field_path: str):
        current = candidate
        for part in [segment for segment in field_path.split("__") if segment]:
            if current is None:
                return None
            try:
                current = getattr(current, part)
            except (AttributeError, FieldDoesNotExist):
                return None
        return current

    def _normalize_compare_value(self, value):
        if isinstance(value, models.Model):
            return getattr(value, "pk", None)
        return value

    def _matches_lookup(self, actual, expected, lookup: str) -> bool:
        normalized_actual = self._normalize_compare_value(actual)
        normalized_expected = self._normalize_compare_value(expected)

        if lookup in {"exact", "equals", "", None}:
            return normalized_actual == normalized_expected
        if lookup == "iexact":
            return str(normalized_actual).lower() == str(normalized_expected).lower()
        if lookup == "icontains":
            return str(normalized_expected).lower() in str(normalized_actual).lower()
        if lookup == "startswith":
            return str(normalized_actual).startswith(str(normalized_expected))
        if lookup == "endswith":
            return str(normalized_actual).endswith(str(normalized_expected))
        if lookup == "gt":
            return normalized_actual is not None and normalized_actual > normalized_expected
        if lookup == "gte":
            return normalized_actual is not None and normalized_actual >= normalized_expected
        if lookup == "lt":
            return normalized_actual is not None and normalized_actual < normalized_expected
        if lookup == "lte":
            return normalized_actual is not None and normalized_actual <= normalized_expected
        if lookup == "in":
            if isinstance(normalized_expected, str):
                values = [item.strip() for item in normalized_expected.split(",") if item.strip()]
            else:
                values = list(normalized_expected) if normalized_expected is not None else []
            normalized_values = [self._normalize_compare_value(value) for value in values]
            return normalized_actual in normalized_values
        if lookup == "isnull":
            expected_bool = normalized_expected
            if isinstance(expected_bool, str):
                expected_bool = expected_bool.lower() in {"true", "1", "yes"}
            return (normalized_actual is None) is bool(expected_bool)
        if lookup == "ne":
            return normalized_actual != normalized_expected
        return False
    
    def assign_creator_permission(
            self, 
            model: Type[models.Model],
            field_policy: dict[str|ApplicationField, list[str]|Literal["__all__"]],
            row_permissions: list[str]|Literal["__all__"],
            ):
        """Get or create a reusable "creator" policy for the current user.

        The created policy combines:

        1. field-level permissions from ``field_policy``
        2. row-level permissions on records where ``created_by == current user``
        3. matching global permissions so the granted actions can pass global checks

        This is useful when a user should be allowed to work with records they
        created themselves, while still keeping field-level access more
        restrictive than row-level access.

        Args:
            model (Type[models.Model]): the model to give creator permission for
            field_policy (dict[str|ApplicationField, list[str]|Literal["__all__"]]):
                Dictionary mapping fields to permission lists.

                Keys can be:
                - a field name such as ``"age"``
                - an ``ApplicationField`` instance
                - ``"__all__"`` to apply the same permissions to all fields

                Values can be:
                - a list like ``["add", "view"]`` or ``["add_customer"]``
                - ``"__all__"`` to grant all default model permissions for that
                  field

                Bare permissions like ``"add"`` are normalized to model
                codenames like ``"add_customer"``.

            row_permissions (list[str]|Literal["__all__"]):
                Permissions to grant on rows owned by the current user. These
                are attached to the implicit creator rule
                ``created_by == $user``.

                This is independent from ``field_policy``. For example, a user
                may have row-level ``change`` access to their own records, while
                still being blocked from changing a specific field.

        Usage:
        ```python
        manager.assign_creator_permission(
            Customer,
            field_policy={"__all__": "__all__"},
            row_permissions="__all__",
        )
        ```

        Give full field access and full creator row access for the model.

        ```python
        manager.assign_creator_permission(
            Customer,
            field_policy={
                "first_name": ["add", "view", "change"],
                "last_name": ["add", "view", "change"],
                "age": ["add", "view"],
            },
            row_permissions=["add", "view", "change"],
        )
        ```

        In this example, the user can create and view ``age`` on their own
        records, but cannot change it later because ``change`` is omitted from
        the field-level permission list for that field.

        Repeated calls are additive. Existing creator policies for the same
        user/model are reused and updated instead of duplicated.
        """
        if not isinstance(model, type) or not issubclass(model, models.Model):
            raise TypeError("model must be a Django model class")

        if self.is_anonymous:
            raise ValueError("Cannot assign creator permissions to an anonymous user")

        content_type = ContentType.objects.get_for_model(model)
        creator_field = ApplicationField.get_for_model(model).filter(field="created_by").first()
        if not creator_field:
            raise ValueError("Model must have a created_by application field")

        def normalize_permissions(permissions_value: list[str] | Literal["__all__"]) -> list[str]:
            if permissions_value == "__all__":
                return [
                    create_permission_str(model, permission)
                    for permission in model._meta.default_permissions
                ]

            normalized_permissions = []
            for permission in permissions_value:
                permission_value = str(permission or "").strip()
                if not permission_value:
                    continue

                if "." in permission_value:
                    permission_value = permission_value.split(".", 1)[-1]
                elif "_" not in permission_value:
                    permission_value = create_permission_str(model, permission_value)

                normalized_permissions.append(permission_value)

            return list(dict.fromkeys(normalized_permissions))

        normalized_row_permissions = normalize_permissions(row_permissions)
        if not normalized_row_permissions:
            raise ValueError("At least one row permission must be provided")

        if not isinstance(field_policy, dict) or not field_policy:
            raise ValueError("field_policy must be a non-empty dictionary")

        normalized_field_policy: dict[str, list[str]] = {}

        for field, permissions in field_policy.items():
            normalized_field_permissions = normalize_permissions(permissions)
            if not normalized_field_permissions:
                continue

            if field == "__all__":
                field_key = "__all__"
            elif isinstance(field, ApplicationField):
                if field.content_type_id != content_type.id:
                    raise ValueError("All fields must belong to the given model")
                field_key = str(field.id)
            else:
                field_name = str(field or "").strip()
                if not field_name:
                    continue

                application_field = ApplicationField.get_for_model(model).filter(field=field_name).first()
                if not application_field:
                    raise ValueError(f"Unknown field '{field_name}' for model '{model._meta.model_name}'")
                field_key = str(application_field.id)

            existing_permissions = normalized_field_policy.get(field_key, [])
            normalized_field_policy[field_key] = list(
                dict.fromkeys([*existing_permissions, *normalized_field_permissions])
            )

        if not normalized_field_policy:
            raise ValueError("At least one field permission must be provided")

        all_field_permissions = list(
            dict.fromkeys(
                permission
                for permissions in normalized_field_policy.values()
                for permission in permissions
            )
        )
        all_policy_permissions = list(
            dict.fromkeys([*normalized_row_permissions, *all_field_permissions])
        )

        policy_key = f"{content_type.app_label}.{content_type.model}.{self.user.pk}"

        field_policy_obj, _ = FieldPolicy.objects.get_or_create(
            content_type=content_type,
            name=f"Creator field policy {policy_key}",
            defaults={"rule": {}},
        )

        field_rule = field_policy_obj.rule if isinstance(field_policy_obj.rule, dict) else {}
        field_rule = dict(field_rule)

        for field_key, permissions in normalized_field_policy.items():
            existing_permissions = field_rule.get(field_key, [])
            field_rule[field_key] = list(dict.fromkeys([*existing_permissions, *permissions]))

        if field_policy_obj.rule != field_rule:
            field_policy_obj.rule = field_rule
            field_policy_obj.save(update_fields=["rule"])

        row_policy, _ = RowPolicy.objects.get_or_create(
            content_type=content_type,
            name=f"Creator row policy {policy_key}",
        )

        row_rule_definition = {
            "application_field_id": str(creator_field.id),
            "operator": Lookup.EQUALS_USER.value.id,
            "value": "$user",
        }
        row_rule = row_policy.rules.filter(rule=row_rule_definition).first()
        if not row_rule:
            row_rule = row_policy.rules.create(rule=row_rule_definition)
        row_rule.add_permissions(normalized_row_permissions)

        policy, _ = Policy.objects.get_or_create(
            name=f"Creator policy {policy_key}",
            defaults={
                "description": f"Creator permissions for {content_type.app_label}.{content_type.model}",
                "row_policy": row_policy,
                "field_policy": field_policy_obj,
            },
        )

        fields_to_update = []
        if policy.row_policy_id != row_policy.id:
            policy.row_policy = row_policy
            fields_to_update.append("row_policy")
        if policy.field_policy_id != field_policy_obj.id:
            policy.field_policy = field_policy_obj
            fields_to_update.append("field_policy")
        if fields_to_update:
            policy.save(update_fields=fields_to_update)

        policy.assign_user(self.user)
        policy.global_permissions.add(
            *Permission.objects.filter(
                content_type=content_type,
                codename__in=all_policy_permissions,
            )
        )

        self.policies = self.get_user_policies()
        return policy
