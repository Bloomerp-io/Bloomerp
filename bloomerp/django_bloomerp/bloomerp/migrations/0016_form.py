import uuid

import bloomerp.model_fields.user_field
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bloomerp", "0015_rename_preference_field_layout_to_layout"),
        ("contenttypes", "0002_remove_content_type_name"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Form",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("datetime_created", models.DateTimeField(auto_now_add=True)),
                ("datetime_updated", models.DateTimeField(auto_now=True)),
                ("avatar", models.ImageField(blank=True, null=True, upload_to="avatars/")),
                ("layout", models.JSONField(blank=True, default=dict)),
                ("requires_review", models.BooleanField(default=True)),
                (
                    "content_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="contenttypes.contenttype",
                    ),
                ),
                (
                    "created_by",
                    bloomerp.model_fields.user_field.UserField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)s_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "updated_by",
                    bloomerp.model_fields.user_field.UserField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)s_updated",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "abstract": False,
                "default_permissions": (
                    "add",
                    "change",
                    "delete",
                    "view",
                    "bulk_change",
                    "bulk_delete",
                    "bulk_add",
                    "export",
                ),
            },
        ),
    ]
