from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.models import Permission

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
    rule = models.JSONField(
        help_text=_("A JSON representation of the row-level access control rule.")
    )
    permissions = models.ManyToManyField(
            to=Permission,
            related_name="row_policy_rules",            
        )
    
    
    