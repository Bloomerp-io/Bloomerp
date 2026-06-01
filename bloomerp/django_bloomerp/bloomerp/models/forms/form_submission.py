from django.db import models

from bloomerp.models.base_bloomerp_model import BloomerpModel, FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.definition import BloomerpModelConfig
from bloomerp.models.mixins.timestamp_model_mixin import TimestampModelMixin

class FormSubmission(BloomerpModel):
    bloomerp_config = BloomerpModelConfig(
        layout=FieldLayout(
            rows=[
                LayoutRow(
                    title="Details",
                    columns=2,
                    items=[
                        LayoutItem(id="form"),
                        LayoutItem(id="persisted"),
                        LayoutItem(id="data", colspan=2)
                    ]
                )
            ]
        )
    )
    
    avatar = None
    
    form = models.ForeignKey(
        to="bloomerp.Form",
        on_delete=models.SET_NULL, # We probs don't wanna lose all of our submissions if the form is deleted.
        blank=False,
        null=True
    )
    data : dict = models.JSONField()
    persisted = models.BooleanField(
        default=False,
        help_text="Whether the form was persisted"
    )
    
    def __str__(self):
        return f"{self.form} - {self.datetime_created}"
    