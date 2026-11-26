import bloomerp.models.communication.calendar.validators
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    """Set the Python-side booking default without rewriting stored timezones."""

    dependencies = [("bloomerp", "0113_workflow_notify_on_completion")]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="calendarbooking",
                    name="timezone",
                    field=models.CharField(
                        default=django.utils.timezone.get_default_timezone_name,
                        max_length=255,
                        validators=[
                            bloomerp.models.communication.calendar.validators.validate_calendar_timezone
                        ],
                        verbose_name="Availability timezone",
                    ),
                ),
            ],
        ),
    ]
