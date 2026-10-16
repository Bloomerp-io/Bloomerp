"""Bring existing standard calendar preferences in line with the declared Inbox grouping default."""

from typing import ClassVar

from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def set_default_calendar_colors(
    apps: Apps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    """Add Inbox grouping to standard CalendarEvent preferences without replacing custom groupings."""
    preference_model = apps.get_model("bloomerp", "UserListViewPreference")
    preferences = preference_model.objects.using(schema_editor.connection.alias).filter(
        content_type__app_label="bloomerp",
        content_type__model="calendarevent",
        name="Calendar",
        view_type="calendar",
    )
    for preference in preferences.iterator():
        options = dict(preference.options or {})
        calendar = dict(options.get("calendar") or {})
        if calendar.get("color_grouping_field"):
            continue
        calendar["color_grouping_field"] = "inboxes"
        options["calendar"] = calendar
        preference.options = options
        preference.save(update_fields=["options"])


class Migration(migrations.Migration):
    """Update existing defaults once while preserving later user preference changes on rollback."""

    dependencies: ClassVar[list[tuple[str, str]]] = [("bloomerp", "0101_calendar_conference_session")]
    operations: ClassVar[list[migrations.RunPython]] = [
        migrations.RunPython(set_default_calendar_colors, migrations.RunPython.noop)
    ]
