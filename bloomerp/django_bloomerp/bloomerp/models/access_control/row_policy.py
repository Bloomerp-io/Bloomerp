from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from bloomerp.models.mixins import absolute_url_model_mixin

class RowPolicy(absolute_url_model_mixin.AbsoluteUrlModelMixin, models.Model):
    """
    A policy that limits which rows (records) are visible/mutable for a subject.
    """
    class Meta:
        db_table = "bloomerp_access_control_row_policy"
        verbose_name = _("Access Control Row Policy")
        verbose_name_plural = _("Access Control Row Policies")
        
    content_type = models.ForeignKey(
        to=ContentType,
        on_delete=models.CASCADE,
    )
    name = models.CharField(
        max_length=255, 
        blank=True, 
        default="",
        help_text=_("The name of the row-level access control policy.")
        )
    
    def __str__(self):
        return f"{self.name} ({self.content_type.app_label}.{self.content_type.model})"
    
    def validate_rule(self):
        """
        Validates the rule defined for this RowPolicy.
        Raises ValidationError if the rule is invalid.
        """
        # Placeholder for actual rule validation logic
        if False:  # Replace with actual validation condition
            raise ValidationError(_("The rule defined for this RowPolicy is invalid."))
        
        pass

    def clean(self):
        self.validate_rule()
        super().clean()


