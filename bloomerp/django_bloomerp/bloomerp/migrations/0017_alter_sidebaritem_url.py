from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bloomerp", "0016_sidebaritem_color_alter_sidebar_user"),
    ]

    operations = [
        migrations.AlterField(
            model_name="sidebaritem",
            name="url",
            field=models.CharField(
                blank=True,
                help_text="URL that the sidebar item points to.",
                max_length=2048,
                null=True,
            ),
        ),
    ]
