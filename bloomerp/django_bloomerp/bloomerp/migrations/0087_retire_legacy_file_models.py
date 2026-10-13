"""Retire legacy tables after checking the additive file-node storage cutover.

The preceding migration preserves file UUIDs, storage keys, metadata, and usages.
Legacy generated folders and template folder destinations are retired; physical
organization now belongs to FileNode. No storage deletion runs during migration.
"""

from typing import ClassVar

from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.operations.base import Operation
from django.db.migrations.state import StateApps


def verify_file_cutover(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Refuse to drop a legacy file whose UUID and storage key have not been preserved."""
    database = schema_editor.connection.alias
    files = apps.get_model("bloomerp", "File").objects.using(database)
    nodes = apps.get_model("bloomerp", "FileNode").objects.using(database)
    preserved = nodes.filter(
        pk=models.OuterRef("pk"), kind="FILE", content=models.OuterRef("file")
    )
    if files.annotate(_preserved=models.Exists(preserved)).filter(_preserved=False).exists():
        raise RuntimeError(
            "Legacy files are not fully represented by FileNode storage keys. "
            "Reconcile the file-node cutover before retiring legacy tables."
        )


class Migration(migrations.Migration):
    """Remove old model state and tables while retaining the file-node snapshot."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("bloomerp", "0086_file_nodes_and_object_references"),
    ]
    operations: ClassVar[list[Operation]] = [
        migrations.RunPython(verify_file_cutover),
        migrations.RemoveField(model_name="documenttemplate", name="save_to_folder"),
        # Drop the referencing table intact; removing its fields first breaks its constraints.
        migrations.DeleteModel(name="FileFieldReference"),
        migrations.DeleteModel(name="File"),
        migrations.DeleteModel(name="FileFolder"),
    ]
