from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.contrib.contenttypes.models import ContentType
from bloomerp.models import ApplicationField

class RowPolicyRule(models.Model):
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
    
    def validate_rule(self):
        """Checks whether the rule is valid

        Returns:
            bool: whether the rule is valid or not
        """
        # NOTE: we assume that each row policy rule
        # contains one and only one application field
        # for now. This behavior could change in the future
        application_field_id = self.rule.get("application_field_id")
        if not application_field_id:
            raise ValidationError("Missing application field id in rule")
        try:
            application_field = ApplicationField.objects.get(id=application_field_id)
        except ApplicationField.DoesNotExist:
            raise ValidationError("Incorrect application field")
        
        # Check if the application field is related to the content type
        if not application_field.content_type == self.content_type:
            raise ValidationError("Content type of the application field does not match that of the field policy")
        
        
        # Get the field type
        operator = self.rule.get("operator")
        if not operator:
            raise ValidationError("Missing operator")
        
        field_type = application_field.get_field_type_enum()
        if not any([operator == field.value.id for field in field_type.lookups]):
            raise ValidationError("Invalid operator")
        
        value = self.rule.get("value")
        if not value:
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
    
    def save(self, *args, **kwargs):
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
    
        
    