from django.core.exceptions import ValidationError
from django.db import models


class ContentLayoutModelMixin(models.Model):
    """
    A mixin for models that need to have a content layout.
    """
    class Meta:
        abstract = True

    content_layout = models.JSONField(default=dict)

    items_field_name: str = None  # The name of the field that contains the items in the layout, is a many to many field
    max_rows: int = None  # The maximum number of rows in the layout
    max_columns: int = None  # The maximum number of columns in each row
    max_items: int = None  # The maximum number of items in each column

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Check if the items_field_name is defined
        if not self.items_field_name:
            raise NotImplementedError(f"{self.__class__.__name__} must define items_field_name.")

        # Check if the items_field_name exists in the model and is a many to many field
        items_field = self._meta.get_field(self.items_field_name)
        if not items_field.many_to_many:
            raise ValueError(f"{self.items_field_name} must be a many to many field.")

    def generate_layout(self) -> dict:
        """
        Generates a layout based on the items in the many-to-many field.
        """
        items = getattr(self, self.items_field_name).all()
        layout = {"rows": []}
        row = {"size": 12, "columns": []}
        column = {"size": 12 // self.max_columns, "items": []}

        for item in items:
            if len(column["items"]) >= self.max_items:
                row["columns"].append(column)
                column = {"size": 12 // self.max_columns, "items": []}
                if len(row["columns"]) >= self.max_columns:
                    layout["rows"].append(row)
                    row = {"size": 12, "columns": []}
                    if len(layout["rows"]) >= self.max_rows:
                        break
            column["items"].append(item.pk)

        if column["items"]:
            row["columns"].append(column)
        if row["columns"]:
            layout["rows"].append(row)

        return layout

    def clean(self):
        """
        Validates the content layout.
        """
        layout: dict = self.content_layout
        errors = []

        # Check if layout is a dictionary
        if not isinstance(layout, dict):
            errors.append(ValidationError("Content layout must be a dictionary.", code='invalid'))

        # Check if layout contains 'rows' key
        if 'rows' not in layout:
            errors.append(ValidationError("Content layout must contain 'rows' key.", code='missing_rows'))

        # Check if the row count is within the limits
        if 'rows' in layout and len(layout.get('rows')) > self.max_rows:
            errors.append(ValidationError(f"Content layout exceeds the maximum number of rows ({self.max_rows}).", code='max_rows_exceeded'))

        # Get the set of valid item IDs from the many-to-many field
        items_field = self._meta.get_field(self.items_field_name)
        valid_item_ids = set(items_field.related_model.objects.values_list('id', flat=True))

        # Check if the column count is within the limits
        if 'rows' in layout:
            for row in layout.get('rows'):
                if len(row.get('columns')) > self.max_columns:
                    errors.append(ValidationError(f"Row exceeds the maximum number of columns ({self.max_columns}).", code='max_columns_exceeded'))

                # Check if the item count is within the limits
                for column in row.get('columns'):
                    if len(column.get('items')) > self.max_items:
                        errors.append(ValidationError(f"Column exceeds the maximum number of items ({self.max_items}).", code='max_items_exceeded'))

                    # Check if the item IDs are valid
                    for item in column.get('items'):
                        if item not in valid_item_ids:
                            errors.append(ValidationError(f"Invalid item ID {item} in content layout.", code='invalid_item_id'))

        # Raise all collected errors at once
        if errors:
            raise ValidationError({'content_layout': errors})

        # Call the clean method of the superclass
        super().clean()

    def save(self, *args, **kwargs):
        """
        Overrides the save method to generate the layout if it's empty or needs to be updated.
        """
        super().save(*args, **kwargs)
        if not self.content_layout:
            self.content_layout = self.generate_layout()
            super().save(update_fields=['content_layout'])