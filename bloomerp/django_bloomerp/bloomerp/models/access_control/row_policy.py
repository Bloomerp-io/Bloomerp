from __future__ import annotations
from tabnanny import verbose

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

class RowPolicy(models.Model):
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



