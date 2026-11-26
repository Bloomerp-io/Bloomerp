from typing import ClassVar

from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.operations.base import Operation


def rename_application_field(
    apps: Apps, schema_editor: BaseDatabaseSchemaEditor, old_name: str, new_name: str
) -> None:
    """Keep existing grants and layouts attached to the same application field ID."""
    fields = (
        apps.get_model("bloomerp", "ApplicationField")
        .objects.using(schema_editor.connection.alias)
        .filter(
            content_type__app_label="bloomerp",
            content_type__model="bookinglinksubmission",
        )
    )
    if not fields.filter(field=new_name).exists():
        fields.filter(field=old_name).update(field=new_name, db_column=f"{new_name}_id")


def rename_booking_link_field(
    apps: Apps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    """Update the registry to match the submission's new foreign key name."""
    rename_application_field(apps, schema_editor, "calendar_booking", "booking_link")


def restore_booking_link_field(
    apps: Apps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    """Restore the original registry name on migration reversal."""
    rename_application_field(apps, schema_editor, "booking_link", "calendar_booking")


class Migration(migrations.Migration):
    """Preserve existing submissions while adding public scheduling fields."""

    dependencies: ClassVar[list[tuple[str, str]]] = [("bloomerp", "0115_booking_links")]

    operations: ClassVar[list[Operation]] = [
        migrations.RenameField(
            model_name="bookinglinksubmission",
            old_name="calendar_booking",
            new_name="booking_link",
        ),
        migrations.RunPython(rename_booking_link_field, restore_booking_link_field),
        migrations.AddField(
            model_name="bookinglink",
            name="auto_approve",
            field=models.BooleanField(default=True, verbose_name="Auto approve"),
        ),
        migrations.AddField(
            model_name="bookinglinksubmission",
            name="requested_start",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="Requested start"
            ),
        ),
        migrations.AddField(
            model_name="bookinglinksubmission",
            name="requested_end",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="Requested end"
            ),
        ),
    ]
