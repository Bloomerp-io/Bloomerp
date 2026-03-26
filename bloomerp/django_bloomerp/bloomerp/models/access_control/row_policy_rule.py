from django.db import models
from enum import Enum
from typing import Optional
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.contrib.contenttypes.models import ContentType
from bloomerp.models import ApplicationField
from bloomerp.models.mixins import AbsoluteUrlModelMixin

class RowPolicyRule(AbsoluteUrlModelMixin, models.Model):
    """
    Model representing a rule within a row-level access control policy.
    """
    class Meta:
        db_table = "bloomerp_access_control_row_policy_rule"
        verbose_name = _("Access Control Row Policy Rule")
        verbose_name_plural = _("Access Control Row Policy Rules")
    
    row_policy = models.ForeignKey(
        "RowPolicy",
        related_name="rules",
        on_delete=models.CASCADE,
        help_text=_("The row-level access control policy this rule belongs to.")
    )
    rule : dict = models.JSONField(
        help_text=_("A JSON representation of the row-level access control rule.")
    )
    permissions = models.ManyToManyField(
            to=Permission,
            related_name="row_policy_rules",
            through="RowPolicyRulePermission"            
        )
    
    @property
    def content_type(self) -> ContentType:
        return getattr(self.row_policy, "content_type", None)   
    
    def add_permission(self, permission:str|Permission):
        """Adds a permission using a permission string

        Args:
            permission (str | Permission): the permission string or object
        """
        # Accept either a Permission instance or a codename string.
        if isinstance(permission, Permission):
            if not self.is_valid_permission(permission):
                raise ValueError("Permission content type does not match RowPolicy content type")
            self.permissions.add(permission)
            return

        # Treat string as a permission codename scoped to this rule's RowPolicy content type
        codename = permission
        content_type = getattr(self.row_policy, "content_type", None)
        if content_type is None:
            raise ValueError("RowPolicy or its content_type is not set on this rule")

        try:
            perm = Permission.objects.get(codename=codename, content_type=content_type)
        except Permission.DoesNotExist as exc:
            raise ValueError(f"Permission with codename '{codename}' for content type '{content_type}' does not exist") from exc

        self.permissions.add(perm)
    
    def add_permissions(self, permissions:list[str | Permission]):
        """Adds permissions using a list of strings

        Args:
            permissions (list[str | Permission]): a list of permission strings or objects
        """
        for p in permissions:
            self.add_permission(p)
            
    def is_valid_permission(self, permission:str|Permission) -> bool:
        """Checks whether a given permission is valid to add to a policy
        rule. Permissions are considered to be invalid to add when it is not related to
        the currect content type

        Args:
            permission (Permission): _description_

        Returns:
            bool: whether the permission is valid for this row policy rule
        """
        # Resolve Permission instance if a codename string is provided
        content_type = self.content_type
        if content_type is None:
            return False

        if isinstance(permission, Permission):
            return permission.content_type_id == content_type.id

        # permission is a codename string: check for existence scoped to this content type
        codename = permission
        return Permission.objects.filter(codename=codename, content_type=content_type).exists()
    
    def _resolve_lookup(self, field_type, operator: str):
        """Resolves a lookup by id, django representation, or alias."""
        if not operator or not field_type:
            return None

        for lookup in field_type.lookups:
            if operator == lookup.value.id:
                return lookup
            if operator == lookup.value.django_representation:
                return lookup
            if operator in (lookup.value.aliases or []):
                return lookup
        return None

    def _is_valid_related_path(self, model_cls, path: str) -> bool:
        if not model_cls or not path:
            return False

        parts = [part for part in path.split("__") if part]
        if not parts:
            return False

        current_model = model_cls
        for idx, part in enumerate(parts):
            try:
                field = current_model._meta.get_field(part)
            except Exception:
                # Allow lookup suffix on final segment
                return idx == len(parts) - 1

            if idx == len(parts) - 1:
                return True

            if not getattr(field, "is_relation", False):
                return False

            current_model = field.related_model
            if current_model is None:
                return False

        return True

    def _is_valid_related_path_by_fields(self, content_type, path: str) -> bool:
        if not content_type or not path:
            return False

        parts = [part for part in path.split("__") if part]
        if not parts:
            return False

        current_content_type = content_type
        for idx, part in enumerate(parts):
            app_field = ApplicationField.objects.filter(
                content_type=current_content_type,
                field=part,
            ).first()

            if not app_field:
                return False

            if idx == len(parts) - 1:
                return True

            if not app_field.related_model_id:
                return False

            current_content_type = app_field.related_model
            if current_content_type is None:
                return False

        return False

    def validate_rule(self):
        """Checks whether the rule is valid

        Returns:
            bool: whether the rule is valid or not
        """
        application_field_id = self.rule.get("application_field_id")
        if not application_field_id:
            raise ValidationError("Missing application field id in rule")

        try:
            application_field = ApplicationField.objects.get(id=application_field_id)
        except ApplicationField.DoesNotExist:
            raise ValidationError("Incorrect application field")

        operator = self.rule.get("operator")
        if not operator:
            raise ValidationError("Missing operator")

        field_path = self.rule.get("field")
        if isinstance(field_path, str) and "__" in field_path:
            if not (
                self._is_valid_related_path_by_fields(self.content_type, field_path)
                or self._is_valid_related_path(self.content_type.model_class(), field_path)
            ):
                raise ValidationError("Invalid operator")
        elif isinstance(operator, str) and operator.startswith("__"):
            path = operator.lstrip("_")
            if not (
                self._is_valid_related_path_by_fields(self.content_type, path)
                or self._is_valid_related_path(self.content_type.model_class(), path)
            ):
                raise ValidationError("Invalid operator")
        else:
            # Check if the application field is related to the content type
            if not application_field.content_type == self.content_type:
                raise ValidationError("Content type of the application field does not match that of the field policy")

            field_type = application_field.get_field_type_enum()
            if not self._resolve_lookup(field_type, str(operator)):
                raise ValidationError("Invalid operator")

        value = self.rule.get("value")
        if value is None or value == "":
            raise ValidationError("No value given")
        
    def is_valid_rule(self) -> bool:
        """Checks whether a rule is valud

        Returns:
            bool: the result
        """
        try:
            self.is_valid_rule()
        except Exception as e:
            return False
        return True
        
    def clean(self):
        self.validate_rule()
    
    def _normalize_rule(self):
        if not isinstance(self.rule, dict):
            return

        rule = dict(self.rule)
        operator = rule.get("operator")
        if isinstance(operator, Enum):
            operator = operator.value
        if hasattr(operator, "id") and isinstance(operator.id, str):
            rule["operator"] = operator.id

        rule["operator"] = rule.get("operator")
        self.rule = rule

    def save(self, *args, **kwargs):
        self._normalize_rule()
        self.full_clean()
        return super().save(*args, **kwargs)
    
    @property
    def operator_str(self):
        """
        Returns the operator as a display name
        """
        pass
        
    def __str__(self):
        try:
            return f"{self.rule.get("field")} {self.rule.get("operator")} {self.rule.get("value")}"
        except Exception as e:
            return super().__str__()
    

class RowPolicyRulePermission(models.Model):
    class Meta:
        managed = True
        db_table = "bloomerp_row_policy_rule_permission"
    
    row_policy_rule = models.ForeignKey(RowPolicyRule, on_delete=models.CASCADE)
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE)

    def clean(self):
        rp = self.row_policy_rule.row_policy
        if rp.content_type_id != self.permission.content_type_id:
            raise ValidationError(
                "Permission content type must match RowPolicy content type"
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
    
        
    
