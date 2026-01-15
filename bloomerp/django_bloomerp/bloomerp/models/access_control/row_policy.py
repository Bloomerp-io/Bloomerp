from __future__ import annotations

import os
from typing import Any, Optional

from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Model, Q
from django.db.models.query import QuerySet
from rest_framework import serializers

from bloomerp.models.application_field import ApplicationField

class RowPolicyChoice(models.TextChoices):
    VIEW = "view", "View"
    ADD = "add", "Add"
    CHANGE = "change", "Change"
    DELETE = "delete", "Delete"
    BULK_ADD = "bulk_add", "Bulk Add"
    BULK_CHANGE = "bulk_change", "Bulk Change"
    BULK_DELETE = "bulk_delete", "Bulk Delete"
    EXPORT = "export", "Export"
    

class RowPolicy(models.Model):
    """
    A policy that limits which rows (records) are visible/mutable for a subject.

    This is intended for dynamic ABAC-style row security.
    - Django model permissions remain the outer gate.
    - RowPolicy further restricts the queryset.

    Rules are stored as JSON and compiled to a safe Django Q() expression.
    
    Example of a JSON rule:
    ```python
    {
        1 : {
            "expression" : "equals",
            "value" : "1",
            "action" : [
                1,
                2,
                3
            ]
        },
        2 : {
            "expression" : "is_null",
            "value" : True,
            "action" : [
                1,
                2
            ]
        }
    }
    ```
    In the above example: 
        - the keys `1` and `2` are application_field_id's.
        - the actions are permission id's.
        - the expression and value define the filter to apply on that field.
    
    """
    content_type = models.ForeignKey(
        to=ContentType,
        on_delete=models.CASCADE,
    )
    action = models.CharField(
        max_length=32,
        choices=RowPolicyChoice.choices
    )

    name = models.CharField(max_length=255, blank=True, default="")
    rule = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "bloomerp_row_policy"
        indexes = [
            models.Index(fields=["content_type", "action"]),
        ]

    def __str__(self) -> str:
        subjects = []
        if self.name:
            subjects.append(self.name)
        return f"RowPolicy({self.action}) for {self.content_type}{' - ' + ', '.join(subjects) if subjects else ''}"

    def clean(self) -> None:
        # If you want "global policies" (apply to everyone), remove this validation.
        # For now we keep it permissive: a policy with no users/groups simply won't match anyone.
        if self.rule is not None and not isinstance(self.rule, dict):
            raise ValidationError({"rule": "Rule must be a JSON object."})

    



