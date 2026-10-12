"""Small, explicit authorization boundary for configured telephone lines."""

from django.contrib.auth.models import AnonymousUser
from django.db.models import QuerySet
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.models.communication.voip import VoIPConnection, VoIPNumber, PhoneCall


class VoIPAccessManager:
    """Grant line usage to assigned active staff and connection owners/admins."""

    def __init__(self, user: AbstractBloomerpUser | AnonymousUser) -> None:
        """Use the authenticated actor for every access decision."""
        self.user = user

    def get_connections(self) -> QuerySet[VoIPConnection]:
        """Return accounts this actor may configure or synchronize."""
        if (
            not self.user.is_authenticated
            or not self.user.is_active
            or not self.user.is_staff
        ):
            return VoIPConnection.objects.none()
        if self.user.is_superuser:
            return VoIPConnection.objects.all()
        return VoIPConnection.objects.filter(created_by=self.user)

    def get_numbers(self, *, active: bool = True) -> QuerySet[VoIPNumber]:
        """Return assigned lines; historical access does not require an active carrier."""
        if (
            not self.user.is_authenticated
            or not self.user.is_active
            or not self.user.is_staff
        ):
            return VoIPNumber.objects.none()
        numbers = VoIPNumber.objects.all()
        if not self.user.is_superuser:
            numbers = numbers.filter(assigned_users=self.user)
        if active:
            numbers = numbers.filter(is_active=True, connection__status="active")
        return numbers.distinct()

    def get_calls(self) -> QuerySet[PhoneCall]:
        """Scope history to accessible lines, retaining visibility after disconnect."""
        return PhoneCall.objects.filter(number__in=self.get_numbers(active=False))
