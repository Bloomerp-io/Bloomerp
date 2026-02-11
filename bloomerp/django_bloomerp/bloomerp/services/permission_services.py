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
        self.policies = self.get_user_policies()
    
    def get_user_policies(self) -> QuerySet[Policy]:
        """Retrieve all policies associated with the user.

        Returns:
            QuerySet[Policy]: queryset of policies linked to the user.
        """
        if not self.user:
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
    
    def has_global_permission(self, model : models.Model, permission_str) -> bool:
        pass
    
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
        
    def has_access_to_object(self, object:models.Model, permission_str:str) -> bool:
        """Returns a boolean that checks whether a user has access to a particular object

        Args:
            object (models.Model): the django ORM object

        Returns:
            bool: whether the user has access to the object
        """
        return self.get_queryset(object._meta.model, permission_str).filter(
            id=object.id
        ).exists()
    
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

        combined_q = Q()
        has_any_rule = False

        for row_policy in row_policies:
            for rule_obj in row_policy.rules.all():
                # Only consider rules that grant the requested permission
                perms = getattr(rule_obj, "permissions", None)
                if perms is None:
                    continue

                if permission_value not in {p.codename for p in perms.all()}:
                    continue

                rule_dict = getattr(rule_obj, "rule", None) or {}
                if not isinstance(rule_dict, dict):
                    continue

                application_field_id = rule_dict.get("application_field_id")
                operator_id = rule_dict.get("operator")
                value = rule_dict.get("value")
                field_path = rule_dict.get("field")

                if not application_field_id or not operator_id:
                    continue

                application_field = ApplicationField.objects.filter(id=application_field_id).first()
                if not application_field:
                    continue

                field_name = application_field.field
                operator_str = str(operator_id)

                # Determine field path (supports advanced foreign path filters)
                if isinstance(field_path, str) and "__" in field_path:
                    field_name = field_path
                    lookup_enum = None
                    django_lookup = operator_str
                elif operator_str.startswith("__"):
                    # Operator contains full path (e.g. "__country__name__icontains")
                    field_name = operator_str.lstrip("_")
                    lookup_enum = None
                    django_lookup = ""
                else:
                    lookup_enum = application_field.get_field_type_enum().get_lookup_by_id(operator_str)
                    if not lookup_enum:
                        # Allow django lookup representations (e.g., "icontains")
                        for lookup in application_field.get_field_type_enum().lookups:
                            if lookup.value.django_representation == operator_str:
                                lookup_enum = lookup
                                break
                            if operator_str in (lookup.value.aliases or []):
                                lookup_enum = lookup
                                break

                    django_lookup = (lookup_enum.value.django_representation or "").strip() if lookup_enum else operator_str

                # Special-case: equals current user
                if lookup_enum == Lookup.EQUALS_USER or str(value) == "$user":
                    combined_q |= Q(**{field_name: self.user})
                    has_any_rule = True
                    continue

                if not lookup_enum and operator_str.startswith("__"):
                    # operator contains full field path with lookup already
                    filter_key = field_name
                    try:
                        combined_q |= Q(**{filter_key: value})
                        has_any_rule = True
                    except Exception:
                        continue
                    continue

                if not lookup_enum and django_lookup == operator_str and "__" in field_name:
                    # Advanced field path with operator already normalized
                    filter_key = f"{field_name}__{django_lookup}" if django_lookup else field_name
                    try:
                        combined_q |= Q(**{filter_key: value})
                        has_any_rule = True
                    except Exception:
                        continue
                    continue

                if not lookup_enum and not django_lookup:
                    continue

                # Basic normalization for common lookups
                if lookup_enum == Lookup.IN and isinstance(value, str):
                    # Allow comma-separated lists
                    value = [v.strip() for v in value.split(",") if v.strip()]

                filter_key = f"{field_name}__{django_lookup}" if django_lookup else field_name

                try:
                    combined_q |= Q(**{filter_key: value})
                    has_any_rule = True
                except Exception:
                    # Defensive: ignore malformed rules
                    continue

        if not has_any_rule:
            return model.objects.none()

        return model.objects.filter(combined_q).distinct()
    
    
        
