from django.db import migrations, models


class Migration(migrations.Migration):
    """Add double-click advancement to tutorial step choices."""

    dependencies = [("bloomerp", "0111_tutorials_and_schema_updates")]

    operations = [
        migrations.AlterField(
            model_name="tutorialstep",
            name="advance_mode",
            field=models.CharField(
                choices=[
                    ("manual", "Manually"),
                    ("click", "When clicked"),
                    ("dblclick", "When double-clicked"),
                    ("input", "When typing in an input"),
                    ("navigation", "When navigated to a new URL"),
                    ("delay", "After a delay"),
                ],
                default="manual",
                max_length=10,
                verbose_name="Advance when",
            ),
        ),
    ]
