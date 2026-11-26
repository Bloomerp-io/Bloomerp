from typing import ClassVar

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    """Store the booking location or the automatic conference setting."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("bloomerp", "0116_booking_link_submission")
    ]

    operations: ClassVar[list[Operation]] = [
        migrations.AddField(
            model_name="bookinglink",
            name="location",
            field=models.CharField(blank=True, max_length=255, verbose_name="Location"),
        ),
    ]
