from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("bloomerp", "0011_remove_tile_query_alter_workspace_module_id_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserCreateViewPreference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("field_layout", models.JSONField(default=dict)),
                (
                    "content_type",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, to="contenttypes.contenttype"),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="create_view_preference",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "default_permissions": ("add", "change", "delete", "view", "bulk_change", "bulk_delete", "bulk_add", "export"),
                "db_table": "bloomerp_user_create_view_preference",
                "managed": True,
            },
        ),
    ]
