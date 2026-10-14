from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps


def migrate_view_mode(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Retain each preference's former split-view selection in the new mode field."""
    preference = apps.get_model("bloomerp", "UserListViewPreference")
    preference.objects.using(schema_editor.connection.alias).filter(split_view_enabled=True).update(view_mode="split")


def restore_split_flag(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Restore the old split flag when rolling back the three-mode setting."""
    preference = apps.get_model("bloomerp", "UserListViewPreference")
    preference.objects.using(schema_editor.connection.alias).filter(view_mode="split").update(split_view_enabled=True)


class Migration(migrations.Migration):
    dependencies = [("bloomerp", "0092_conversation_activity")]
    operations = [
        migrations.AddField(
            model_name="userlistviewpreference", name="view_mode",
            field=models.CharField(choices=[("normal", "Normal"), ("split", "Split view"), ("drawer", "Drawer")], default="normal", max_length=10, verbose_name="View mode"),
        ),
        migrations.RunPython(migrate_view_mode, restore_split_flag),
        migrations.RemoveField(model_name="userlistviewpreference", name="split_view_enabled"),
    ]
