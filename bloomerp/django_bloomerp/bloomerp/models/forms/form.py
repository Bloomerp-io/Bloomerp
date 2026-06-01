from django.db import models
from django.contrib.contenttypes.models import ContentType
from bloomerp.models.base_bloomerp_model import BloomerpModel, FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.definition import BloomerpModelConfig
from bloomerp.models.mixins.content_layout_model_mixin import ContentLayoutModelMixin
from django.utils.translation import gettext_lazy as _

class Form(BloomerpModel, ContentLayoutModelMixin, models.Model):
    
    bloomerp_config = BloomerpModelConfig(
        allow_string_search=True,
        layout=FieldLayout(
            rows=[
                LayoutRow(
                    columns=2,
                    title="Details",
                    items=[
                        LayoutItem(id="name"),
                        LayoutItem(id="requires_review"),
                        LayoutItem(id="content_type"),
                        LayoutItem(id="max_submissions"),
                        LayoutItem(id="description", colspan=2),
                    ]
                )
            ]
        )
    )
    
    name = models.CharField(
        max_length=255,
        default="Untitled form",
        help_text=_("The name of the form")
    )
    description = models.TextField(
        null=True,
        blank=True
    )
    requires_review = models.BooleanField(
        default=True,
        help_text=_("Whether the form submission needs to be reviewed before it is persisted.")
    )
    content_type = models.ForeignKey(
        to=ContentType,
        on_delete=models.CASCADE
    )
    max_submissions = models.IntegerField(
        null=True,
        blank=True,
        help_text=_("Maximum number of submissions possible for the form")
    )
    initial_payload = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Initial payload for the form")
    )

    def __str__(self):
        return f"{self.name} - {str(self.content_type)}" 