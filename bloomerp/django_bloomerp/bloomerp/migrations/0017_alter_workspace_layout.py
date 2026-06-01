from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bloomerp", "0016_form"),
    ]

    operations = [
        migrations.AlterField(
            model_name="workspace",
            name="layout",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
