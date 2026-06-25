from django.db import models
from bloomerp.models.base_bloomerp_model import BloomerpModel, FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.definition import BloomerpModelConfig

class TodoLabel(BloomerpModel):
    """
    Model representing a label that can be assigned to to-do items.
    """
    model_config = BloomerpModelConfig(
        allow_string_search=False,
        layout=FieldLayout(
            rows=[
                LayoutRow(
                    title="Label Details",
                    columns=2,
                    items=[
                        LayoutItem(id="name", colspan=1),
                        LayoutItem(id="color", colspan=1),
                    ],
                )
            ]
        )
    )
    
    class Meta:
        managed = True
        db_table = 'bloomerp_todo_label'
    
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=7)  # Hex color code

    def __str__(self):
        return self.name
    
    
    
    