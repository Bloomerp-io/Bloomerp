from typing import ClassVar

import django.db.models.deletion
from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    """Add optional booking email settings and require a message for a sender."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("bloomerp", "0117_booking_link_location")
    ]

    operations: ClassVar[list[Operation]] = [
        migrations.AddField(
            model_name="bookinglink",
            name="email_account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="booking_links",
                to="bloomerp.emailaccount",
                verbose_name="Email account",
            ),
        ),
        migrations.AddField(
            model_name="bookinglink",
            name="email_message",
            field=models.TextField(
                blank=True,
                help_text="Required when an email account is selected.",
                null=True,
                verbose_name="Email message",
            ),
        ),
        migrations.AddConstraint(
            model_name="bookinglink",
            constraint=models.CheckConstraint(
                condition=models.Q(email_account__isnull=True)
                | (models.Q(email_message__isnull=False) & ~models.Q(email_message="")),
                name="booking_link_email_message_required",
                violation_error_message=(
                    "Enter an email message when an email account is selected."
                ),
                violation_error_code="email_message_required",
            ),
        ),
    ]
