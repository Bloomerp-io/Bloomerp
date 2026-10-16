"""Independent Inbox, event-row, and event-date permissions for calendar rendering."""

from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.test import RequestFactory, TestCase

from bloomerp.components.communication.calendar.inbox_calendar import inbox_calendar
from bloomerp.filters.definition import FilterCondition
from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.permissions.definition import RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.tests.communication.inbox_calendar_fixtures import InboxCalendarFixtures


class InboxCalendarPolicyTests(InboxCalendarFixtures, TestCase):
    """Exercise compiled policies at the calendar's rendering boundary."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Populate runtime field definitions for real field-policy evaluation."""
        call_command("save_application_fields", suppress_output=True, verbosity=0)

    def setUp(self) -> None:
        """Create placed meetings and a normal Inbox owner without event grants."""
        super().setUp()
        self.prepare_calendar()

    def test_row_specific_date_denial_does_not_expose_events_or_counts(self) -> None:
        """Only rows whose corresponding date representation is readable enter the grid."""
        common = PolicyManager.create_policy(
            CalendarEvent,
            field_permissions={
                name: ["view"] for name in ("inboxes", "all_day", "cancelled")
            },
            row_permissions=[
                RowPolicyRuleContent(
                    permissions=["view"], connector="AND", conditions=[]
                )
            ],
        )
        dates = PolicyManager.create_policy(
            CalendarEvent,
            field_permissions={name: ["view"] for name in ("start", "end")},
            row_permissions=[
                RowPolicyRuleContent(
                    permissions=["view"],
                    connector="AND",
                    conditions=[
                        FilterCondition(
                            field_path="title",
                            lookup_id="equals",
                            value=self.timed.title,
                        )
                    ],
                )
            ],
        )
        for policy in (common, dates):
            PolicyManager.assign(policy, self.owner)
        hidden = self.create_event("Private date meeting")
        hidden.inboxes.add(self.source)
        request = RequestFactory().get("/calendar/")
        request.user = self.owner
        response = inbox_calendar(request, inbox_id=self.source.pk)
        self.assertContains(response, self.timed.title)
        self.assertNotContains(response, self.all_day.title)
        self.assertNotContains(response, hidden.title)
        self.assertNotContains(response, str(hidden.pk))

    def test_group_row_policy_does_not_expand_inbox_placement(self) -> None:
        """Event grants through a group remain intersected with the selected Inbox's M2M."""
        group = Group.objects.create(name="Inbox calendar viewers")
        self.owner.groups.add(group)
        policy = PolicyManager.create_policy(
            CalendarEvent,
            field_permissions={"__all__": ["view"]},
            row_permissions=[
                RowPolicyRuleContent(
                    permissions=["view"], connector="AND", conditions=[]
                )
            ],
        )
        PolicyManager.assign(policy, group)
        request = RequestFactory().get("/calendar/")
        request.user = self.owner
        response = inbox_calendar(request, inbox_id=self.source.pk)
        self.assertContains(response, self.timed.title)
        self.assertNotContains(response, self.unplaced.title)
        self.assertNotContains(response, self.cancelled.title)

    def test_date_fields_without_placement_permission_are_insufficient(self) -> None:
        """A user must be allowed to see membership in this Inbox calendar as well as dates."""
        policy = PolicyManager.create_policy(
            CalendarEvent,
            field_permissions={
                name: ["view"] for name in ("all_day", "cancelled", "start", "end")
            },
            row_permissions=[
                RowPolicyRuleContent(
                    permissions=["view"], connector="AND", conditions=[]
                )
            ],
        )
        PolicyManager.assign(policy, self.owner)
        request = RequestFactory().get("/calendar/")
        request.user = self.owner
        with self.assertRaises(PermissionDenied):
            inbox_calendar(request, inbox_id=self.source.pk)

    def test_date_only_readers_can_view_all_day_events_without_timed_fields(
        self,
    ) -> None:
        """The adapter must not require timed start/end permissions to show date-only events."""
        policy = PolicyManager.create_policy(
            CalendarEvent,
            field_permissions={
                name: ["view"]
                for name in (
                    "inboxes",
                    "all_day",
                    "cancelled",
                    "start_date",
                    "end_date",
                )
            },
            row_permissions=[
                RowPolicyRuleContent(
                    permissions=["view"], connector="AND", conditions=[]
                )
            ],
        )
        PolicyManager.assign(policy, self.owner)
        request = RequestFactory().get("/calendar/")
        request.user = self.owner
        response = inbox_calendar(request, inbox_id=self.source.pk)
        self.assertContains(response, self.all_day.title)
        self.assertNotContains(response, self.timed.title)
