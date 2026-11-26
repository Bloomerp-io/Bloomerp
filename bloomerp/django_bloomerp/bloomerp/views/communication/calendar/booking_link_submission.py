"""Public scheduling for visitors holding an active booking link."""

from calendar import Calendar, monthrange
from collections import Counter
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

from django import forms
from django.contrib.auth.decorators import login_not_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import formats, timezone
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from bloomerp.models.communication.calendar import BookingLink, CalendarEvent
from bloomerp.router import router
from bloomerp.utils.rich_text import sanitize_html


class BookingLinkSubmissionForm(forms.Form):
    """Validate a visitor's chosen time and contact details."""

    slot = forms.ChoiceField(
        label=_("Choose a time"),
        widget=forms.RadioSelect(attrs={"class": "sr-only"}),
        error_messages={
            "invalid_choice": _(
                "This time is no longer available. Choose another time."
            ),
        },
    )
    name = forms.CharField(
        label=_("Name"),
        max_length=255,
        widget=forms.TextInput(attrs={"autocomplete": "name", "class": "input w-full"}),
    )
    email = forms.EmailField(
        label=_("Email"),
        max_length=254,
        widget=forms.EmailInput(
            attrs={"autocomplete": "email", "class": "input w-full"}
        ),
    )


def booking_date(value: str) -> date | None:
    """Read an ISO calendar date from a visitor's navigation or form."""
    try:
        day = date.fromisoformat(value)
    except ValueError:
        return None
    # Leave room to convert local times on the selected dates to UTC.
    return day if 1 < day.year < 9999 else None


def booking_location_url(location: str) -> str:
    """Link only HTTP and HTTPS locations on the public confirmation."""
    try:
        url = urlsplit(location)
        return location if url.scheme in ("http", "https") and url.hostname else ""
    except ValueError:
        return ""


@router.register(
    path="book/",
    route_type="detail",
    models=[BookingLink],
    url_name="booking_link_submission",
    name="Book an appointment",
    searchable=False,
)
@login_not_required
@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
def booking_link_submission(
    request: HttpRequest, pk: int | UUID, **kwargs: object
) -> HttpResponse:
    """Offer available dates, validate the requested slot, and report its outcome."""
    if not isinstance(pk, UUID):
        raise Http404
    link = get_object_or_404(BookingLink, pk=pk, active=True)
    zone = ZoneInfo(link.timezone)
    url = link.get_public_url()
    salt = f"booking-link-confirmation:{link.pk}"
    confirmation = None
    if request.method == "GET" and request.GET.get("confirmation"):
        try:
            result = signing.loads(
                request.GET["confirmation"], salt=salt, max_age=timedelta(minutes=30)
            )
            confirmation = {
                "start": datetime.fromisoformat(result["start"]),
                "approved": result["approved"],
            }
            if submission_id := result.get("submission_id"):
                event = CalendarEvent.objects.filter(
                    calendar_booking_submission_id=submission_id,
                    calendar_booking_submission__booking_link_id=link.pk,
                    cancelled=False,
                ).first()
                if event is not None:
                    confirmation.update(
                        approved=True,
                        start=event.start,
                        location=event.location,
                        location_url=booking_location_url(event.location),
                    )
        except signing.BadSignature:
            pass

    context: dict[str, object] = {
        "booking_link": link,
        "booking_url": url,
        "confirmation": confirmation,
        "description_html": mark_safe(sanitize_html(link.description)),
    }
    if confirmation is None:
        schedule = link.get_availability()
        today = timezone.now().astimezone(zone).date()
        first_day = max(today, schedule.start_date or today)
        if schedule.end_date and schedule.end_date < first_day:
            first_day = today
        first_month = first_day.replace(day=1)
        last_month = (
            max(first_month, schedule.end_date.replace(day=1))
            if schedule.end_date
            else date(9998, 12, 1)
        )
        params = request.POST if request.method == "POST" else request.GET
        selected_day = booking_date(params.get("day", ""))
        month = booking_date(f"{params.get('month', '')}-01")
        month = (selected_day.replace(day=1) if selected_day else month) or first_month
        month = min(max(first_month, month), last_month)
        last_day = month.replace(day=monthrange(month.year, month.month)[1])
        slots = link.available_slots(month, last_day)
        if selected_day is None or selected_day.replace(day=1) != month:
            selected_day = next(iter(slots), None)

        form = BookingLinkSubmissionForm(
            request.POST if request.method == "POST" else None
        )
        starts = {start.isoformat(): start for start in slots.get(selected_day, ())}
        labels = [
            formats.time_format(start.astimezone(zone)) for start in starts.values()
        ]
        label_counts = Counter(labels)
        form.fields["slot"].choices = [
            (
                value,
                f"{label} {start.astimezone(zone):%Z}"
                if label_counts[label] > 1
                else label,
            )
            for (value, start), label in zip(starts.items(), labels, strict=True)
        ]
        if request.method == "POST" and form.is_valid():
            start = starts[form.cleaned_data["slot"]]
            try:
                submission, approved = link.submit_slot(
                    start=start,
                    name=form.cleaned_data["name"],
                    email=form.cleaned_data["email"],
                    meeting_base_url=request.build_absolute_uri("/"),
                )
            except BookingLink.DoesNotExist:
                raise Http404 from None
            except ValidationError as error:
                form.add_error("slot", error)
            else:
                receipt = signing.dumps(
                    {
                        "start": start.isoformat(),
                        "approved": approved,
                        "submission_id": str(submission.pk) if submission is not None else None,
                    },
                    salt=salt,
                )
                return redirect(f"{url}?confirmation={receipt}")

        context.update(
            form=form,
            month=month,
            previous_month=(month - timedelta(days=1)) if month > first_month else None,
            next_month=(last_day + timedelta(days=1)) if month < last_month else None,
            selected_day=selected_day,
            weekday_labels=[date(2024, 1, day) for day in range(1, 8)],
            weeks=[
                [month.replace(day=day) if day else None for day in week]
                for week in Calendar().monthdayscalendar(month.year, month.month)
            ],
            available_days=slots.keys(),
            has_times=bool(starts),
        )

    response = render(
        request, "views/communication/calendar/booking_link_submission.html", context
    )
    response["Referrer-Policy"] = "same-origin"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response
