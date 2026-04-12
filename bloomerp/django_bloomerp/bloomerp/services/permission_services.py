"""
This module provides services related to permissions management.
Classes:
    BasePermissions (Enum): Defines basic permission types such as READ, WRITE, DELETE, and UPDATE.
Functions:
    has_object_permission(user: User, permission: BasePermission) -> bool:
        Checks if the given user has the specified object-level permission.
"""

"""Services regarding permissions"""
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
from typing import Type
from django.db.models import Q
from bloomerp.field_types import Lookup
from django.core.exceptions import FieldDoesNotExist
    
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
    
    def __init__(self, user: AbstractBloomerpUser):
        self.user = user
        self.is_anonymous = not user or user.is_anonymous
        
        self.policies = self.get_user_policies()
        

    
    def get_user_policies(self) -> QuerySet[Policy]:
        """Retrieve all policies associated with the user.

        Returns:
            QuerySet[Policy]: queryset of policies linked to the user.
        """
        if self.is_anonymous:
            return Policy.objects.none()

        return (
            Policy.objects.filter(
                models.Q(users=self.user) | models.Q(groups__in=self.user.groups.all())
            )
            .distinct()
        )
        
    def get_field_policies(self) -> QuerySet[FieldPolicy]:
        """Retrieve field policies associated with the user.
        
        Returns:
            QuerySet[FieldPolicy]: queryset of field policies linked to the user.
        """
        return FieldPolicy.objects.filter(
            policies__in=self.policies
        ).distinct()
    
    def get_row_policies(self) -> QuerySet[RowPolicy]:
        """Retrieve row policies associated with the user.

        Returns:
            QuerySet[RowPolicy]: queryset of row policies linked to the user.
        """
        return (
            RowPolicy.objects.filter(
                policies__in=self.policies
            )
            .prefetch_related("rules__permissions")
            .distinct()
        )

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
        if self.is_anonymous:
            return False

        if getattr(self.user, "is_superuser", False):
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
            return False

        if "." in permission_value and self.user.has_perm(permission_value):
            return True

        permission_codename = permission_value.split(".", 1)[-1]

        if self.user.has_perm(f"{content_type.app_label}.{permission_codename}"):
            return True

        return self.policies.filter(
            global_permissions__content_type=content_type,
            global_permissions__codename=permission_codename,
        ).exists()

    def get_row_policy_rules(self, model_or_content_type: Type[models.Model] | ContentType, permission_str: str):
        # TODO: Add method description
        if isinstance(model_or_content_type, ContentType):
            content_type = model_or_content_type
        elif issubclass(model_or_content_type, models.Model):
            content_type = ContentType.objects.get_for_model(model_or_content_type)
        else:
            raise TypeError("model_or_content_type must be a Django model class or a ContentType")

        if getattr(self.user, "is_superuser", False):
            return []

        applicable_rules = []
        for row_policy in self.get_row_policies().filter(content_type=content_type):
            for rule_obj in row_policy.rules.all():
                perms = getattr(rule_obj, "permissions", None)
                if perms is None:
                    continue
                if permission_str in {p.codename for p in perms.all()}:
                    applicable_rules.append(rule_obj)
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
        if not field:
            return False

        # Superusers always have field access
        if getattr(self.user, "is_superuser", False):
            return True

        permission_value = str(permission_str)

        policies = self.get_field_policies().filter(content_type=field.content_type)
        if not policies.exists():
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
                        return True
                except Exception:
                    # Defensive: skip malformed keys
                    continue

        return False
    
    def get_accessible_fields(self, model_or_content_type: models.Model | ContentType, permission_str:str) -> QuerySet[ApplicationField]:
        """Returns the application fields with a certain permission.

        Args:
            model_or_content_type (models.Model | ContentType): The model or content type to check fields for.
            permission_str (str): The permission string to check.

        Returns:
            QuerySet[ApplicationField]: Queryset of application fields with the specified permission.
        """
        if not model_or_content_type:
            return ApplicationField.objects.none()

        if isinstance(model_or_content_type, ContentType):
            content_type = model_or_content_type
        elif isinstance(model_or_content_type, models.Model):
            content_type = ContentType.objects.get_for_model(model_or_content_type)
        else:
            content_type = model_or_content_type
        
        # Return all fields if user is superuser
        if self.user.is_superuser:
            return ApplicationField.objects.filter(content_type=content_type)
        
        permission_value = str(permission_str)

        policies = self.get_field_policies().filter(content_type=content_type)
        
        if not policies.exists():
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
                    return ApplicationField.objects.filter(content_type=content_type)

                allowed_field_ids.add(str(field_id))

        if not allowed_field_ids:
            return ApplicationField.objects.none()

        return ApplicationField.objects.filter(
            content_type=content_type,
            id__in=allowed_field_ids
        )
        
    def has_access_to_object(self, object:models.Model, permission_str:str, check_global:bool=True) -> bool:
        """Returns a boolean that checks whether a user has access to a particular object

        Args:
            object (models.Model): the django ORM object
            permission_str (str): the permission to check
            check_global (bool): whether to check the global permission for the object as well. Defaults to true.

        Returns:
            bool: whether the user has access to the object
        """
        if check_global:
            has_global_permission = self.has_global_permission(
                object._meta.model,
                permission_str
            )
        else:
            has_global_permission = True

        has_obj_permission = self.get_queryset(object._meta.model, permission_str).filter(
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
        if isinstance(model_or_content_type, ContentType):
            content_type = model_or_content_type
            model = content_type.model_class()
        elif issubclass(model_or_content_type, models.Model):
            model = model_or_content_type
            content_type = ContentType.objects.get_for_model(model)
        else:
            raise TypeError("model_or_content_type must be a Django model class or a ContentType")

        if model is None:
            return models.QuerySet(model=None).none()  # defensive; should not happen

        if not self.user:
            return model.objects.none()

        # Superusers always see the full queryset
        if getattr(self.user, "is_superuser", False):
            return model.objects.all()

        permission_value = str(permission_str)

        # Find row policies applicable to this content type
        row_policies = self.get_row_policies().filter(content_type=content_type)
        if not row_policies.exists():
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

        return self.build_queryset_from_rule_dicts(content_type, applicable_rule_dicts)

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
    
    
        
