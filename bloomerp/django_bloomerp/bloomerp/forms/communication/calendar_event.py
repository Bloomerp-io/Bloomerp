"""Permission-aware event composition with effective Inbox calendar placement."""

import json
from copy import copy
from datetime import datetime, timedelta
from email.utils import getaddresses
from typing import Any
from zoneinfo import ZoneInfo, available_timezones

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import (
    ImproperlyConfigured,
    PermissionDenied,
    ValidationError,
)
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from bloomerp.communication.utils.permissions import accessible_inboxes
from bloomerp.form_fields.text_editor_field import TextEditorFormField
from bloomerp.models.communication.calendar import (
    CalendarEvent,
    CalendarEventParticipant,
)
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.services.email_composer_services import accessible_email_accounts
from bloomerp.services.sectioned_layout_services import get_layout_widget_attrs

COMMON_CREATE_FIELDS = {
    "title",
    "organizer_email",
    "inboxes",
    "organizing_inbox",
    "all_day",
}
TIMED_CREATE_FIELDS = {"start", "end", "event_timezone"}
DATE_CREATE_FIELDS = {"start_date", "end_date"}


def calendar_timezone_choices(reference: datetime) -> list[tuple[str, str]]:
    """Label IANA timezone choices with their GMT offset at the supplied aware instant."""
    choices: list[tuple[str, str]] = []
    for name in sorted(available_timezones()):
        offset = reference.astimezone(ZoneInfo(name)).utcoffset() or timedelta()
        minutes = int(offset.total_seconds() / 60)
        hours, remaining = divmod(abs(minutes), 60)
        sign = "+" if minutes >= 0 else "-"
        choices.append(
            (name, f"(GMT{sign}{hours:02d}:{remaining:02d}) {name.replace('_', ' ')}")
        )
    return choices


def calendar_create_fields(
    user: AbstractBloomerpUser, instance: CalendarEvent | None = None
) -> set[str]:
    """Return writable composition fields for creation or a readable existing event."""
    manager = UserPolicyManager(user)
    if instance is not None:
        if not manager.has_access_to_object(instance, "view") or not manager.has_access_to_object(instance, "change"):
            return set()
        readable = manager.get_accessible_fields_for_object(instance, "view")
        return set(manager.get_accessible_fields_for_object(instance, "change").filter(
            pk__in=readable.values("pk")
        ).values_list("field", flat=True))
    if not manager.has_global_permission(CalendarEvent, "add"):
        return set()
    return set(
        manager.get_accessible_fields(CalendarEvent, "add").values_list(
            "field", flat=True
        )
    )


def can_create_calendar_event(
    user: AbstractBloomerpUser, instance: CalendarEvent | None = None
) -> bool:
    """Require the common composer fields and the existing event's writable date representation."""
    fields = calendar_create_fields(user, instance)
    if instance is not None:
        required = DATE_CREATE_FIELDS if instance.all_day else TIMED_CREATE_FIELDS
        return (COMMON_CREATE_FIELDS | required) <= fields
    return COMMON_CREATE_FIELDS <= fields and (
        TIMED_CREATE_FIELDS <= fields or DATE_CREATE_FIELDS <= fields
    )


class CalendarEventCreateForm(forms.Form):
    """Compose a meeting without exposing scheduling internals or inaccessible calendars."""

    inbox = forms.ModelChoiceField(
        queryset=Inbox.objects.none(),
        label=_("Calendar"),
        empty_label=_("Choose a calendar"),
    )
    title = forms.CharField(max_length=255, label=_("Event title"))
    sender = forms.ModelChoiceField(
        queryset=EmailAccount.objects.none(),
        required=False,
        label=_("Send from"),
        empty_label=_("No email invitation"),
    )
    send_invitations = forms.BooleanField(
        required=False,
        label=_("Email invitations"),
        help_text=_(
            "Selected users receive the event in their calendar. Enable email invitations to also send invites from the selected account."
        ),
    )
    attendee_users = forms.CharField(required=False, widget=forms.HiddenInput)
    event_timezone = forms.ChoiceField(label=_("Timezone"), required=False)
    create_conference = forms.BooleanField(
        required=False, label=_("Add Bloomerp meeting")
    )
    attendees = forms.CharField(
        required=False,
        label=_("Participants"),
        help_text=_(
            "Select users to add this event to their calendar, or enter email addresses."
        ),
    )
    all_day = forms.BooleanField(required=False, label=_("All day"))
    start_date = forms.DateField(
        label=_("Start date"),
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )
    start_time = forms.TimeField(
        required=False,
        label=_("Start time"),
        widget=forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
    )
    end_date = forms.DateField(
        label=_("End date"),
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )
    end_time = forms.TimeField(
        required=False,
        label=_("End time"),
        widget=forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
    )
    location = forms.CharField(required=False, max_length=255, label=_("Location"))
    content = TextEditorFormField(required=False, label=_("Description"))

    def __init__(
        self,
        *args: Any,
        user: AbstractBloomerpUser,
        meeting_base_url: str = "",
        instance: CalendarEvent | None = None,
        **kwargs: Any,
    ) -> None:
        """Reuse the composer with object-specific read/write permissions when editing."""
        super().__init__(*args, **kwargs)
        self.user = user
        self.meeting_base_url = meeting_base_url
        self.original = instance
        self.instance: CalendarEvent | None = None
        self.permission = "change" if instance is not None else "add"
        self.writable_fields = calendar_create_fields(user, instance)
        if not can_create_calendar_event(user, instance):
            raise PermissionDenied
        self.can_create_timed = TIMED_CREATE_FIELDS <= self.writable_fields
        self.can_create_all_day = DATE_CREATE_FIELDS <= self.writable_fields
        self.fields["inbox"].queryset = accessible_inboxes(user).order_by("name")
        self.fields["sender"].queryset = accessible_email_accounts(user).filter(
            status=EmailAccount.Status.ACTIVE
        )
        self.fields["event_timezone"].choices = calendar_timezone_choices(
            timezone.now()
        )
        self.fields["event_timezone"].initial = timezone.get_current_timezone_name()
        self.internal_attendees: list[AbstractBloomerpUser] = []
        self.attendee_calendars: list[Inbox] = []
        for name in ("content", "location"):
            if name not in self.writable_fields:
                del self.fields[name]
        if not {"conference_session", "location"} <= self.writable_fields:
            del self.fields["create_conference"]
        manager = UserPolicyManager(user)
        if instance is not None and "attendees" in self.fields and any(
            not manager.has_access_to_object(participant, "view", fields=["email", "user"])
            for participant in instance.participants.all()
        ):
            del self.fields["attendees"]
        if instance is not None and "attendees" in self.fields:
            participants = list(instance.participants.select_related("user"))
            if any(
                person.user_id and not manager.has_access_to_object(person.user, "view", fields=["email"])
                for person in participants
            ):
                del self.fields["attendees"]
            else:
                self.internal_attendees = [person.user for person in participants if person.user_id]
                self.initial["attendees"] = ", ".join(person.email for person in participants if person.email)
                self.initial["attendee_users"] = json.dumps([str(person.pk) for person in self.internal_attendees])
        if instance is not None:
            self.initial["sender"] = self.fields["sender"].queryset.filter(
                email_address__iexact=instance.organizer_email
            ).values_list("pk", flat=True).first()
            if instance.conference_session_id:
                self.fields.pop("create_conference", None)
        if not self.can_create_timed or not self.can_create_all_day:
            self.fields["all_day"].disabled = True
            self.initial["all_day"] = not self.can_create_timed
        for name, field in self.fields.items():
            css = (
                "select w-full bg-white"
                if isinstance(field.widget, forms.Select)
                else "input input-sm w-full bg-white"
            )
            if name == "all_day" or isinstance(field.widget, forms.CheckboxInput):
                css = "checkbox checkbox-sm"
            elif name == "content":
                css = "min-h-48"
            field.widget.attrs["class"] = css
            field.widget.attrs["aria-label"] = field.label
        for name in ("content", "location"):
            if name in self.fields:
                widget = self.fields[name].widget
                widget.attrs.update(get_layout_widget_attrs(widget=widget))
        self.fields["title"].widget.attrs.update(
            {
                "placeholder": _("Event title"),
                "autofocus": True,
                "class": "input w-full bg-white",
            }
        )
        self.fields["all_day"].widget.attrs["x-model"] = "allDay"
        for name in ("start_time", "end_time"):
            self.fields[name].widget.attrs[":disabled"] = "allDay"
        for name, placeholder in (
            ("attendees", _("Add guests by email")),
            ("location", _("Add a location")),
            ("content", _("Add a description or meeting notes")),
        ):
            if name in self.fields:
                self.fields[name].widget.attrs["placeholder"] = placeholder

    def clean_attendees(self) -> list[str]:
        """Parse the email composer's display-name addresses and deduplicate mailboxes."""
        raw = (
            self.cleaned_data.get("attendees", "").replace(";", ",").replace("\n", ",")
        )
        emails = list(
            dict.fromkeys(
                address.strip().lower()
                for _, address in getaddresses([raw])
                if address.strip()
            )
        )
        if len(emails) > 100:
            raise ValidationError(_("Add no more than 100 guests."))
        for email in emails:
            validate_email(email)
        return emails

    def clean_attendee_users(self) -> list[str]:
        """Resolve explicitly selected user identities through row and email field permissions."""
        try:
            identifiers = json.loads(self.cleaned_data.get("attendee_users") or "[]")
            if (
                not isinstance(identifiers, list)
                or len(identifiers) > 100
                or any(not isinstance(item, str) for item in identifiers)
            ):
                raise ValueError
            identifiers = list(dict.fromkeys(identifiers))
        except (ValueError, TypeError):
            raise ValidationError(_("Invalid selected users.")) from None
        manager = UserPolicyManager(self.user)
        if identifiers and "attendees" not in self.fields:
            raise ValidationError(_("You cannot add internal attendees."))
        model = get_user_model()
        try:
            users = (
                list(
                    manager.get_accessible_queryset(model, "view").filter(
                        pk__in=identifiers, is_active=True
                    )
                )
                if identifiers and manager.has_global_permission(model, "view")
                else []
            )
        except (ValueError, ValidationError):
            raise ValidationError(_("Invalid selected users.")) from None
        if len(users) != len(identifiers) or any(
            not manager.has_access_to_object(person, "view", fields=["email"])
            for person in users
        ):
            raise ValidationError(_("One or more selected users are unavailable."))
        emails = [person.email.lower() for person in users if person.email]
        if len(emails) != len(set(emails)):
            raise ValidationError(
                _("Selected users must have distinct email addresses.")
            )
        self.internal_attendees = users
        for person in users:
            selected = Inbox.objects.filter(user=person, selected=True).first()
            if selected is None:
                raise ValidationError(_("A selected user has no selected calendar."))
            self.attendee_calendars.append(selected.effective_preference)
        return identifiers

    def clean(self) -> dict[str, Any]:
        """Validate one temporal pair and convert inclusive all-day UI dates to exclusive storage."""
        data = super().clean()
        if self.errors:
            return data
        all_day = data.get("all_day", False)
        if (
            all_day
            and not self.can_create_all_day
            or not all_day
            and not self.can_create_timed
        ):
            raise ValidationError(_("You cannot create this type of event."))
        if data.get("create_conference"):
            from bloomerp.communication.builtins.conferencing.configuration import (
                get_conferencing_settings,
            )

            try:
                get_conferencing_settings()
            except ImproperlyConfigured:
                self.add_error(
                    "create_conference",
                    _("Conferencing is unavailable for this instance."),
                )
                return data
        first, last = data["start_date"], data["end_date"]
        organizer_email = self.original.organizer_email if self.original is not None else (
            self.user.email or f"user-{self.user.pk}@calendar.invalid"
        )
        if data.get("sender"):
            organizer_email = data["sender"].email_address
        values: dict[str, Any] = {
            "title": data["title"],
            "organizer_email": organizer_email,
            "organizing_inbox": data["inbox"],
            "all_day": all_day,
            "updated_by": self.user,
        }
        for name in ("content", "location"):
            if name in data:
                values[name] = data[name]
        if data.get("send_invitations"):
            sender = data.get("sender")
            if (
                sender is None
                or not InboxFolder.objects.filter(
                    inbox=data["inbox"], type="email", related_object_id=str(sender.pk)
                ).exists()
            ):
                self.add_error(
                    "sender",
                    _("Choose a sending account linked to this calendar inbox."),
                )
            if not data.get("attendees") and not self.internal_attendees:
                self.add_error(
                    None, _("Add at least one attendee to email invitations.")
                )
            if any(not person.email for person in self.internal_attendees):
                self.add_error(
                    None,
                    _("All attendees need an email address to receive invitations."),
                )
            if self.errors:
                return data
        if all_day:
            if last < first:
                self.add_error(
                    "end_date", _("End date must be on or after the start date.")
                )
                return data
            values.update(start_date=first, end_date=last + timedelta(days=1))
        else:
            for name in ("start_time", "end_time"):
                if not data.get(name):
                    self.add_error(name, _("Enter a time."))
            if self.errors:
                return data
            zone = data.get("event_timezone") or timezone.get_current_timezone_name()
            with timezone.override(ZoneInfo(zone)):
                start = forms.DateTimeField().clean(
                    datetime.combine(first, data["start_time"])
                )
                end = forms.DateTimeField().clean(
                    datetime.combine(last, data["end_time"])
                )
            if end <= start:
                self.add_error("end_time", _("End must be after the start."))
                return data
            values.update(
                start=start,
                end=end,
                event_timezone=zone,
            )
        if self.original is None:
            self.instance = CalendarEvent(created_by=self.user, **values)
        else:
            self.instance = copy(self.original)
            for name, value in values.items():
                setattr(self.instance, name, value)
            self.instance.start = values.get("start")
            self.instance.end = values.get("end")
            self.instance.start_date = values.get("start_date")
            self.instance.end_date = values.get("end_date")
            self.instance.event_timezone = values.get("event_timezone")
        try:
            self.instance.full_clean()
        except ValidationError as error:
            for message in error.messages:
                self.add_error(None, message)
        return data

    def save(self) -> CalendarEvent:
        """Save the event, calendar placement, and permitted guests in one transaction."""
        if not self.is_valid() or self.instance is None:
            raise ValueError("Validate the event form before saving")
        manager = UserPolicyManager(self.user)
        if not manager.candidate_matches_row_policies(self.instance, self.permission):
            raise PermissionDenied(
                _("You cannot update events in this calendar.") if self.original is not None
                else _("You cannot create events in this calendar.")
            )
        with transaction.atomic():
            self.instance.save()
            if "attendees" in self.fields or self.original is None:
                self.instance.inboxes.set(
                    [self.cleaned_data["inbox"], *self.attendee_calendars]
                )
            else:
                self.instance.inboxes.add(self.cleaned_data["inbox"])
            internal_emails = {
                person.email.lower()
                for person in self.internal_attendees
                if person.email
            }
            retained: list[Any] = []
            for person in self.internal_attendees:
                participant, _created = CalendarEventParticipant.objects.get_or_create(
                    event=self.instance, user=person, defaults={"email": person.email}
                )
                retained.append(participant.pk)
            for email in self.cleaned_data.get("attendees", []):
                if email not in internal_emails:
                    participant, _created = CalendarEventParticipant.objects.get_or_create(
                        event=self.instance, email=email, defaults={"user": None}
                    )
                    retained.append(participant.pk)
            if self.original is not None and "attendees" in self.fields:
                removed = self.instance.participants.exclude(pk__in=retained)
                for participant in removed:
                    if not manager.has_access_to_object(participant, "delete"):
                        raise PermissionDenied(_("You cannot remove these participants."))
                removed.delete()
            if self.cleaned_data.get("create_conference"):
                from bloomerp.services.calendar_conferencing import (
                    reserve_calendar_conference,
                )

                link = reserve_calendar_conference(
                    self.instance,
                    self.user,
                    self.internal_attendees,
                    self.meeting_base_url,
                )
                self.instance.location = " · ".join(
                    filter(None, [self.instance.location, link])
                )
                if len(self.instance.location) > 255:
                    raise ValidationError(
                        _("The location and generated meeting link are too long.")
                    )
                self.instance.save(update_fields=["location"])
            if self.cleaned_data.get("send_invitations"):
                from bloomerp.communication.calendar.outgoing import (
                    _attendees,
                    require_event_access,
                )

                require_event_access(
                    self.user,
                    self.instance,
                    write_fields=[
                        "sequence",
                        "scheduling_dtstamp",
                        "cancelled",
                        "invitation_sent_at",
                    ],
                )
                _attendees(self.user, self.instance)
        return self.instance
