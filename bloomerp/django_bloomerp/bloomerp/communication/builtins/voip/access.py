"""Small, explicit authorization boundary for configured telephone lines."""

from django.contrib.auth.models import AnonymousUser
from django.db.models import QuerySet
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.models.communication.voip import VoIPConnection, VoIPNumber, PhoneCall


class VoIPAccessManager:
    """Grant line usage to assigned active staff and users with connection change permission."""

    def __init__(self, user: AbstractBloomerpUser | AnonymousUser) -> None:
        """Use the authenticated actor for every access decision."""
        self.user = user

    def get_connections(self) -> QuerySet[VoIPConnection]:
        """Return accounts this actor has permission to change."""
        if (
            not self.user.is_authenticated
            or not self.user.is_active
            or not self.user.is_staff
        ):
            return VoIPConnection.objects.none()
        manager = UserPolicyManager(self.user)
        if not manager.has_global_permission(VoIPConnection, "change"):
            return VoIPConnection.objects.none()
        return manager.get_accessible_queryset(VoIPConnection, "change")

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
