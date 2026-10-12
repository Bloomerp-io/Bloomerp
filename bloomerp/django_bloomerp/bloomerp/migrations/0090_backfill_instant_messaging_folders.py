"""Provide the default messaging folder to personal inboxes created before IM."""

from typing import ClassVar

from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def backfill_messaging_folders(
    apps: Apps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    """Add missing messaging folders without touching shared or reference inboxes."""
    inbox_model = apps.get_model("bloomerp", "Inbox")
    folder_model = apps.get_model("bloomerp", "InboxFolder")
    database_alias = schema_editor.connection.alias
    inboxes = (
        inbox_model.objects.using(database_alias)
        .filter(
            user__isnull=False,
            source_object__isnull=True,
            shared_with_users__isnull=True,
            shared_with_groups__isnull=True,
        )
        .exclude(folders__type="instant_messaging")
    )
    for inbox_id in inboxes.values_list("pk", flat=True).iterator():
        folder_model.objects.using(database_alias).get_or_create(
            inbox_id=inbox_id, type="instant_messaging"
        )


class Migration(migrations.Migration):
    """Backfill folders while preserving them and their items during rollback."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("bloomerp", "0089_im_message_editor_content")
    ]

    operations: ClassVar[list[migrations.RunPython]] = [
        migrations.RunPython(backfill_messaging_folders, migrations.RunPython.noop),
    ]
