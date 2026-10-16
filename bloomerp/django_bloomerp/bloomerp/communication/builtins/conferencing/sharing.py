"""Capability-based meeting links and host-controlled, browser-bound admission."""

from uuid import UUID, uuid4

from bloomerp.models.communication.conferencing import (
    ConferenceAdmission,
    ConferenceParticipant,
    ConferenceSession,
)
from bloomerp.models.users.user import AbstractBloomerpUser
from django.core import signing
from django.core.exceptions import (
    ImproperlyConfigured,
    PermissionDenied,
    ValidationError,
)
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpRequest
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from .access import authorized_session, require_participant
from .configuration import get_conferencing_settings
from .controller import IDENTITY_SALT, ConferenceController, session_payload
from .livekit import LiveKitClient


def sharing_allowed(session: ConferenceSession) -> bool:
    """Resolve sharing through the source provider without granting access to its chat."""
    try:
        get_conferencing_settings()
    except ImproperlyConfigured:
        return False
    host = (
        session.participants.select_related("user")
        .filter(role="host", user__is_active=True)
        .first()
    )
    event = getattr(session, "calendar_event", None)
    if event is not None and event.cancelled:
        return False
    if host is None:
        return False
    if session.room.conversation_id:
        from bloomerp.communication.builtins.instant_messaging.calling import (
            call_capabilities,
        )

        return call_capabilities(host.user, session.room.conversation).share_links
    return True


def sharing_controls(
    session: ConferenceSession, participant: ConferenceParticipant
) -> dict[str, str]:
    """Supply optional controls to any authorized conference browser driver."""
    if not sharing_allowed(session):
        return {}
    result = {
        "share_url": reverse(
            "conference_sessions_meeting", kwargs={"token": session.share_token}
        )
    }
    if participant.role == "host":
        result["admissions_url"] = reverse(
            "components_conferencing_waiting", kwargs={"session_id": session.pk}
        )
    return result


def shared_session(token: UUID) -> ConferenceSession:
    """Resolve live or calendar-reserved links without exposing closed or cancelled meetings."""
    session = (
        ConferenceSession.objects.select_related("room__conversation")
        .filter(
            Q(status__in=["ringing", "active"])
            | Q(status="pending", calendar_event__isnull=False),
            share_token=token,
            room__archived=False,
        )
        .first()
    )
    if session is None or not sharing_allowed(session):
        raise Http404(_("This meeting link is no longer available."))
    return session


def browser_admission(
    request: HttpRequest, session: ConferenceSession
) -> ConferenceAdmission | None:
    """Bind a request to the visitor's session cookie and current account identity."""
    key = request.session.get("meeting_admissions", {}).get(str(session.pk))
    if not key:
        return None
    user_id = request.user.pk if request.user.is_authenticated else None
    if request.user.is_authenticated and not request.user.is_active:
        raise PermissionDenied
    return session.admissions.filter(browser_key=key, user_id=user_id).first()


def account_presentation(
    user: AbstractBloomerpUser, session: ConferenceSession
) -> dict[str, str]:
    """Reuse the IM participant identity for account visitors and fall back to their profile."""
    if session.room.conversation_id:
        from bloomerp.communication.builtins.instant_messaging.presentation import (
            participant_identity,
        )

        member = (
            session.room.conversation.participants.select_related(
                "user", "identity", "conversation"
            )
            .filter(user=user, left_at__isnull=True)
            .first()
        )
        if member:
            return participant_identity(member, user.pk)
    name = user.get_full_name() or str(user)
    return {
        "displayName": name,
        "initials": "".join(part[0] for part in name.split()[:2]),
        "avatar": user.avatar.url if user.avatar else "",
    }


def request_admission(request: HttpRequest, token: UUID) -> ConferenceAdmission:
    """Queue one visitor per browser and meeting, never accepting a supplied account name."""
    session = shared_session(token)
    if request.user.is_authenticated and not request.user.is_active:
        raise PermissionDenied
    name = (
        account_presentation(request.user, session)["displayName"]
        if request.user.is_authenticated
        else request.POST.get("name", "").strip()
    )
    if not name or len(name) > 255:
        raise ValidationError(_("Enter a name of up to 255 characters."))
    with transaction.atomic():
        session = ConferenceSession.objects.select_for_update().get(pk=session.pk)
        if session.status not in {"pending", "ringing", "active"}:
            raise Http404
        existing = browser_admission(request, session)
        if existing:
            return existing
        if session.admissions.filter(status="waiting").count() >= 100:
            raise ValidationError(
                _("The waiting room is full. Please try again later.")
            )
        admission = ConferenceAdmission.objects.create(
            session=session,
            user=request.user if request.user.is_authenticated else None,
            display_name=name,
        )
    bindings = request.session.get("meeting_admissions", {})
    bindings[str(session.pk)] = str(admission.browser_key)
    request.session["meeting_admissions"] = bindings
    return admission


def host_session(request: HttpRequest, session_id: UUID) -> ConferenceSession:
    """Require the currently authorized host, including current provider eligibility."""
    session = authorized_session(request.user, session_id)
    if (
        require_participant(request.user, session).role != "host"
        or session.status not in {"ringing", "active"}
        or not sharing_allowed(session)
    ):
        raise PermissionDenied
    return session


def decide_admission(
    request: HttpRequest, session_id: UUID, admission_id: UUID
) -> None:
    """Serialize host decisions against call closure and capacity before creating a participant."""
    decision = request.POST.get("decision")
    if decision not in {"admit", "reject"}:
        raise ValidationError(_("Choose whether to admit this guest."))
    host_session(request, session_id)
    with transaction.atomic():
        ConferenceSession.objects.select_for_update().get(pk=session_id)
        session = host_session(request, session_id)
        admission = (
            session.admissions.select_for_update().filter(pk=admission_id).first()
        )
        if admission is None:
            raise Http404
        if admission.status != "waiting":
            return
        if decision == "reject":
            admission.status = "rejected"
        else:
            if admission.user_id and not admission.user.is_active:
                raise PermissionDenied
            participant = (
                session.participants.filter(user_id=admission.user_id).first()
                if admission.user_id
                else None
            )
            if participant is None:
                if (
                    session.participants.count()
                    >= get_conferencing_settings().max_participants
                ):
                    raise ValidationError(_("This meeting is full."))
                participant = ConferenceParticipant.objects.create(
                    session=session,
                    user=admission.user,
                    display_name_snapshot=admission.display_name,
                    invitation_status="accepted",
                    responded_at=timezone.now(),
                )
            admission.participant = participant
            admission.status = "admitted"
        admission.save()


def admitted_participant(participant: ConferenceParticipant) -> bool:
    """Validate a host-admitted guest for webhook reconciliation without chat membership."""
    return (
        (participant.user_id is None or participant.user.is_active)
        and participant.admissions.filter(status="admitted").exists()
        and sharing_allowed(participant.session)
    )


def guest_credentials(request: HttpRequest, token: UUID) -> dict[str, str]:
    """Issue short-lived media credentials only for this browser's admitted identity."""
    with transaction.atomic():
        session = shared_session(token)
        ConferenceSession.objects.select_for_update().get(pk=session.pk)
        session.refresh_from_db()
        if session.status not in {"ringing", "active"}:
            raise Http404
        admission = browser_admission(request, session)
        if (
            admission is None
            or admission.status != "admitted"
            or admission.participant_id is None
        ):
            raise PermissionDenied
        participant = admission.participant
        host = session.participants.select_related("user").get(role="host")
        video = screen = True
        if session.room.conversation_id:
            from bloomerp.communication.builtins.instant_messaging.calling import (
                call_capabilities,
            )

            capabilities = call_capabilities(host.user, session.room.conversation)
            video, screen = capabilities.video, capabilities.screen_share
        presentation = {
            "displayName": admission.display_name,
            "initials": "".join(part[0] for part in admission.display_name.split()[:2]),
            "avatar": "",
        }
        if request.user.is_authenticated:
            presentation = account_presentation(request.user, session)
        identity = signing.Signer(salt=IDENTITY_SALT).sign_object(
            {"participant": str(participant.pk), "nonce": uuid4().hex}, compress=True
        )
        credentials = LiveKitClient().issue_join_credentials(
            session.livekit_room_name,
            identity,
            presentation["displayName"],
            allow_video=video,
            allow_screen_share=screen,
            presentation=presentation,
        )
        return {
            **session_payload(session),
            "join_url": reverse(
                "components_conferencing_guest_join", kwargs={"token": token}
            ),
            "end_url": "",
            "driver": ConferenceController(host.user).browser_driver(session),
            "url": credentials.url,
            "token": credentials.token,
            "can_video": str(video).lower(),
            "can_screen_share": str(screen).lower(),
            "can_end": "false",
            "share_url": sharing_controls(session, participant)["share_url"],
        }
