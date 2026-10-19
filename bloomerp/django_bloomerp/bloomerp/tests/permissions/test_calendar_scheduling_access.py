"""Enforce independent row and field policy on outbound scheduling actions."""

from unittest.mock import patch

from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.test import TestCase

from bloomerp.communication.calendar.outgoing import send_calendar_request
from bloomerp.filters.definition import FilterCondition
from bloomerp.models.communication.calendar import (
    CalendarEvent,
    CalendarEventParticipant,
)
from bloomerp.permissions.definition import RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.tests.communication.calendar_fixtures import SchedulingFixtures


class CalendarSchedulingPolicyTests(SchedulingFixtures, TestCase):
    """Exercise real compiled policies rather than mocking permission decisions."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Populate runtime field metadata used by object-level policy checks."""
        call_command("save_application_fields", suppress_output=True, verbosity=0)

    def setUp(self) -> None:
        """Create an Inbox owner and a local event without implicit calendar grants."""
        super().setUp()
        self.prepare_calendar()
        self.event = self.local_event()

    def test_direct_row_grant_without_writable_fields_cannot_send(self) -> None:
        """Calendar read fields and row changes do not imply writable scheduling metadata."""
        policy = PolicyManager.create_policy(
            CalendarEvent,
            field_permissions={"__all__": ["view"]},
            row_permissions=[
                RowPolicyRuleContent(
                    permissions=["view", "change"], connector="AND", conditions=[]
                )
            ],
        )
        PolicyManager.assign(policy, self.owner)
        with (
            patch("bloomerp.communication.calendar.outgoing._send") as send,
            self.assertRaises(PermissionDenied),
        ):
            send_calendar_request(
                user=self.owner,
                event_id=self.event.pk,
                email_account_id=self.account.pk,
            )
        send.assert_not_called()

    def test_field_grants_do_not_override_row_scope(self) -> None:
        """A policy for other meetings cannot authorize a guessed event ID."""
        policy = PolicyManager.create_policy(
            CalendarEvent,
            field_permissions={"__all__": ["view", "change"]},
            row_permissions=[
                RowPolicyRuleContent(
                    permissions=["view", "change"],
                    connector="AND",
                    conditions=[
                        FilterCondition(
                            field_path="title",
                            lookup_id="equals",
                            value="Another meeting",
                        )
                    ],
                )
            ],
        )
        PolicyManager.assign(policy, self.owner)
        with (
            patch("bloomerp.communication.calendar.outgoing._send") as send,
            self.assertRaises(PermissionDenied),
        ):
            send_calendar_request(
                user=self.owner,
                event_id=self.event.pk,
                email_account_id=self.account.pk,
            )
        send.assert_not_called()

    def test_group_grants_allow_scheduling_through_an_accessible_sender(self) -> None:
        """A permitted normal user can send using the existing group policy mechanism."""
        group = Group.objects.create(name="Calendar schedulers")
        self.owner.groups.add(group)
        for model in (CalendarEvent, CalendarEventParticipant):
            policy = PolicyManager.create_policy(
                model,
                field_permissions={"__all__": ["view", "change"]},
                row_permissions=[
                    RowPolicyRuleContent(
                        permissions=["view", "change"], connector="AND", conditions=[]
                    )
                ],
            )
            PolicyManager.assign(policy, group)
        with patch(
            "bloomerp.communication.calendar.outgoing._send", return_value="<sent@test>"
        ) as send:
            send_calendar_request(
                user=self.owner,
                event_id=self.event.pk,
                email_account_id=self.account.pk,
            )
        self.assertEqual(send.call_count, 1)
