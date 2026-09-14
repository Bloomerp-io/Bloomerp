from enum import Enum

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.contrib.contenttypes.models import ContentType
from bloomerp.models import ApplicationField
from bloomerp.field_types.registry import FieldTypeDefinition
from bloomerp.models.mixins.absolute_url_model_mixin import AbsoluteUrlModelMixin
from bloomerp.permissions.definition import RowPolicyRuleContent
from bloomerp.filters.definition import FilterCondition
from pydantic import ValidationError as PydanticValidationError

ROW_POLICY_DISALLOWED_FIELD_TYPE_IDS = {
    "Property",
}

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
        help_text=_("The row-level access control policy this rule belongs to."),
        verbose_name=_("Row Policy"),
    )
    rule : dict = models.JSONField(
        help_text=_("A JSON representation of the row-level access control rule."),
        verbose_name=_("Rule"),
    )
    permissions = models.ManyToManyField(
            to=Permission,
            related_name="row_policy_rules",
            through="RowPolicyRulePermission"            ,
        verbose_name=_("Permissions"),
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
    
    def validate_rule_condition(self, condition: FilterCondition):
        """Validates the rule condition

        Args:
            condition (FilterCondition): the rule condition

        Raises:
            ValidationError: _description_
            ValidationError: _description_
        """
        from bloomerp.filters.compiler import resolve_condition
        from bloomerp.filters.resolver import FilterFieldResolver, resolve_lookup

        model = self.content_type.model_class()
        field, target = FilterFieldResolver.for_model(model).resolve(condition.field_path)
        lookup = resolve_lookup(field, target, condition.lookup_id)
        if lookup.nested:
            raise ValidationError("A row condition requires a terminal lookup")
        if field.context.field_type.id in ROW_POLICY_DISALLOWED_FIELD_TYPE_IDS:
            raise ValidationError("Properties and one-to-many fields cannot be used in row policies")
        # Runtime values are bound by the permission compiler, not at save time.
        if condition.value != "$user" and condition.lookup_id != "equals_user":
            resolve_condition(condition, model=model)

    def validate_rule(self):
        """Checks whether the rule is valid

        Returns:
            bool: whether the rule is valid or not
        """
        try:
            rule_content = RowPolicyRuleContent.model_validate(self.rule)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc)) from exc

        if rule_content._legacy_content_type_ids - {self.content_type.pk}:
            raise ValidationError("Field belongs to a different content type")
        for condition in rule_content.conditions:
            self.validate_rule_condition(condition)
        
    def is_valid_rule(self) -> bool:
        """Checks whether a rule is valud

        Returns:
            bool: the result
        """
        try:
            self.validate_rule()
        except Exception:
            return False
        return True
        
    def clean(self):
        self.validate_rule()
    
    def _normalize_rule(self):
        if not isinstance(self.rule, dict):
            return

        for condition in self.rule.get("conditions", []):
            if not isinstance(condition, dict):
                continue

            operator = condition.get("operator")
            if isinstance(operator, Enum):
                operator = operator.value
            if hasattr(operator, "id") and isinstance(operator.id, str):
                condition["operator"] = operator.id

            condition["operator"] = condition.get("operator")

        try:
            normalized = RowPolicyRuleContent.model_validate(self.rule)
            if normalized._legacy_content_type_ids - {self.content_type.pk}:
                raise ValidationError("Field belongs to a different content type")
            self.rule = normalized.model_dump(exclude={"permissions"})
        except PydanticValidationError:
            return

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
            rule_content = RowPolicyRuleContent.model_validate(self.rule)
            if not rule_content.conditions:
                return "All rows" if rule_content.connector == "AND" else "No rows"
            labels = [
                f"{condition.field_path} {condition.lookup_id} {condition.value}"
                for condition in rule_content.conditions
            ]
            return f" {rule_content.connector} ".join(labels)
        except Exception:
            return super().__str__()
    

class RowPolicyRulePermission(models.Model):
    class Meta:
        verbose_name = _("Row Policy Rule Permission")
        verbose_name_plural = _("Row Policy Rule Permissions")
        managed = True
        db_table = "bloomerp_row_policy_rule_permission"
    
    row_policy_rule = models.ForeignKey(RowPolicyRule, on_delete=models.CASCADE, verbose_name=_("Row Policy Rule"))
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, verbose_name=_("Permission"))

    def clean(self):
        rp = self.row_policy_rule.row_policy
        if rp.content_type_id != self.permission.content_type_id:
            raise ValidationError(
                "Permission content type must match RowPolicy content type"
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
    
        
    
