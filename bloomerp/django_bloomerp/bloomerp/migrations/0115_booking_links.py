import uuid
from typing import ClassVar

import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models
from django.db.migrations.operations.base import Operation

import bloomerp.model_fields.user_field
import bloomerp.models.communication.calendar.validators


class Migration(migrations.Migration):
    """Recreate booking storage and detach retained events from discarded submissions."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("bloomerp", "0114_calendar_booking_default_timezone"),
    ]

    operations: ClassVar[list[Operation]] = [
        migrations.RemoveField(
            model_name="calendarevent",
            name="calendar_booking_submission",
        ),
        migrations.DeleteModel(
            name="CalendarBookingSubmission",
        ),
        migrations.DeleteModel(
            name="CalendarBooking",
        ),
        migrations.CreateModel(
            name="BookingLink",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "datetime_created",
                    models.DateTimeField(
                        auto_now_add=True, verbose_name="Datetime Created"
                    ),
                ),
                (
                    "datetime_updated",
                    models.DateTimeField(
                        auto_now=True, verbose_name="Datetime Updated"
                    ),
                ),
                ("title", models.CharField(max_length=255, verbose_name="Title")),
                (
                    "description",
                    models.TextField(blank=True, verbose_name="Description"),
                ),
                (
                    "meeting_duration_minutes",
                    models.PositiveIntegerField(
                        validators=[django.core.validators.MinValueValidator(1)],
                        verbose_name="Meeting duration in minutes",
                    ),
                ),
                (
                    "availability_hours",
                    models.JSONField(
                        blank=True, default=dict, verbose_name="Availability hours"
                    ),
                ),
                (
                    "timezone",
                    models.CharField(
                        default=django.utils.timezone.get_default_timezone_name,
                        max_length=255,
                        validators=[
                            bloomerp.models.communication.calendar.validators.validate_calendar_timezone
                        ],
                        verbose_name="Availability timezone",
                    ),
                ),
                (
                    "public_token",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                ("active", models.BooleanField(default=False, verbose_name="Active")),
                (
                    "created_by",
                    bloomerp.model_fields.user_field.UserField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)s_created",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created By",
                    ),
                ),
                (
                    "organizing_inbox",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="organized_calendar_bookings",
                        to="bloomerp.inbox",
                        verbose_name="Organizing inbox",
                    ),
                ),
                (
                    "target_inboxes",
                    models.ManyToManyField(
                        blank=True,
                        related_name="calendar_bookings",
                        to="bloomerp.inbox",
                        verbose_name="Destination inboxes",
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
                        verbose_name="Updated By",
                    ),
                ),
            ],
            options={
                "verbose_name": "Booking link",
                "verbose_name_plural": "Booking links",
                "db_table": "bloomerp_calendarbooking",
                "abstract": False,
                "default_permissions": (
                    "add",
                    "change",
                    "delete",
                    "view",
                    "export",
                    "import",
                    "bulk_add",
                    "bulk_change",
                    "bulk_delete",
                ),
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(meeting_duration_minutes__gt=0),
                        name="calendar_booking_positive_duration",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="BookingLinkSubmission",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "datetime_created",
                    models.DateTimeField(
                        auto_now_add=True, verbose_name="Datetime Created"
                    ),
                ),
                (
                    "datetime_updated",
                    models.DateTimeField(
                        auto_now=True, verbose_name="Datetime Updated"
                    ),
                ),
                ("name", models.CharField(max_length=255, verbose_name="Name")),
                ("email", models.EmailField(max_length=254, verbose_name="Email")),
                (
                    "submitted_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now, verbose_name="Submitted at"
                    ),
                ),
                (
                    "calendar_booking",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="submissions",
                        to="bloomerp.bookinglink",
                        verbose_name="Booking link",
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
                        verbose_name="Created By",
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
                        verbose_name="Updated By",
                    ),
                ),
            ],
            options={
                "verbose_name": "Booking link submission",
                "verbose_name_plural": "Booking link submissions",
                "db_table": "bloomerp_calendarbookingsubmission",
                "abstract": False,
                "default_permissions": (
                    "add",
                    "change",
                    "delete",
                    "view",
                    "export",
                    "import",
                    "bulk_add",
                    "bulk_change",
                    "bulk_delete",
                ),
            },
        ),
        migrations.AddField(
            model_name="calendarevent",
            name="calendar_booking_submission",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="calendar_event",
                to="bloomerp.bookinglinksubmission",
                verbose_name="Booking submission",
            ),
        ),
    ]
