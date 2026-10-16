"""Calendar composer capabilities use real model and field add grants."""

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from bloomerp.forms.communication.calendar_event import (
    COMMON_CREATE_FIELDS,
    TIMED_CREATE_FIELDS,
    CalendarEventCreateForm,
    can_create_calendar_event,
)
from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.permissions.manager import PolicyManager


class CalendarCreationPolicyTests(TestCase):
    """Keep inbox ownership separate from event and guest creation capabilities."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Populate the field metadata consumed by the production policy compiler."""
        call_command("save_application_fields", suppress_output=True, verbosity=0)

    def setUp(self) -> None:
        """Create an ordinary calendar owner with no implicit event permissions."""
        self.user = get_user_model().objects.create_user(
            username="calendar-composer-policy", is_staff=True
        )
        self.inbox = Inbox.objects.create(user=self.user, name="Policy calendar")

    def test_model_add_without_composition_fields_is_not_enough(self) -> None:
        """A model-level grant cannot bypass the required composer field grants."""
        policy = PolicyManager.create_policy(
            CalendarEvent,
            global_permissions=["add"],
            field_permissions={},
            row_permissions=[],
        )
        PolicyManager.assign(policy, self.user)
        self.assertFalse(can_create_calendar_event(self.user))

    def test_timed_field_grants_do_not_grant_all_day_or_guest_creation(self) -> None:
        """Offer only the permitted representation and omit unrelated optional and guest writes."""
        policy = PolicyManager.create_policy(
            CalendarEvent,
            global_permissions=["add"],
            row_permissions=[],
            field_permissions={
                name: ["add"] for name in COMMON_CREATE_FIELDS | TIMED_CREATE_FIELDS
            },
        )
        PolicyManager.assign(policy, self.user)
        self.assertTrue(can_create_calendar_event(self.user))
        form = CalendarEventCreateForm(user=self.user)
        self.assertTrue(form.can_create_timed)
        self.assertFalse(form.can_create_all_day)
        self.assertTrue(form.fields["all_day"].disabled)
        self.assertNotIn("attendees", form.fields)
        self.assertNotIn("content", form.fields)
        self.assertNotIn("location", form.fields)
