"""Named presets; saving never changes workspace or dataview defaults."""
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from pydantic import TypeAdapter, ValidationError as SchemaValidationError

from bloomerp.filters.definition import Filters
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.definition import BloomerpModelConfig


def validate_filter_groups(value):
    try:
        TypeAdapter(Filters).validate_python(value, strict=True)
    except SchemaValidationError as exc:
        raise ValidationError(_("Invalid grouped filters.")) from exc


class SavedFilter(BloomerpModel):
    """A shared preset identified by its model/workspace scope and record ID."""
    bloomerp_config = BloomerpModelConfig(is_internal=True)

    class Meta(BloomerpModel.Meta):
        db_table = "bloomerp_filter"
        ordering = ["name", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["scope", "identifier", "name"], name="unique_saved_filter_scope_name"),
            models.CheckConstraint(check=models.Q(scope__in=["model", "workspace"]), name="saved_filter_valid_scope"),
        ]

    name = models.CharField(max_length=255)
    filters = models.JSONField(default=list, blank=True, validators=[validate_filter_groups])
    scope = models.CharField(max_length=16, choices=[("model", _("Model")), ("workspace", _("Workspace"))])
    identifier = models.CharField(max_length=255)

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        self.name = self.name.strip() if isinstance(self.name, str) else self.name
        self.identifier = self.identifier.strip() if isinstance(self.identifier, str) else self.identifier
        if not self.name or not self.identifier:
            raise ValidationError(_("A name and scope identifier are required."))
        validate_filter_groups(self.filters)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
    
