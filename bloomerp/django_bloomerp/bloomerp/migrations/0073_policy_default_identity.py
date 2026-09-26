from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("bloomerp", "0072_filefolder_system_identity")]

    operations = [
        migrations.AddField(
            model_name="policy", name="system_created",
            field=models.BooleanField(default=False, editable=False),
        ),
        migrations.AddField(
            model_name="policy", name="default_policy_key",
            field=models.CharField(
                max_length=512, unique=True, null=True, blank=True, editable=False,
            ),
        ),
        migrations.AddField(
            model_name="policy", name="default_policy_hash",
            field=models.CharField(max_length=64, blank=True, default="", editable=False),
        ),
    ]
