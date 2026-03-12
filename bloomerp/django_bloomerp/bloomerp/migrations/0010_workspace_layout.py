from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bloomerp", "0009_remove_tileonworkspace_widget_alter_activitylog_user_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspace",
            name="layout",
            field=models.JSONField(default=dict),
        ),
    ]
