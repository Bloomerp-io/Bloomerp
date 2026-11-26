"""Bind Booking Link email choices to the account access of the current user."""

from typing import TYPE_CHECKING, Any

from django import forms
from django.db.models import QuerySet

from bloomerp.widgets.booking_email_account_widget import BookingEmailAccountWidget

if TYPE_CHECKING:
    from bloomerp.models.communication.email_account import EmailAccount


class BookingEmailAccountField(forms.ModelChoiceField):
    """Restrict newly selected senders while allowing a saved sender to remain."""

    widget = BookingEmailAccountWidget

    def __init__(self, queryset: QuerySet["EmailAccount"], **kwargs: Any) -> None:
        """Use the same available accounts as the email composer."""
        from bloomerp.middleware import current_request
        from bloomerp.services.email_composer_services import accessible_email_accounts

        user = getattr(current_request(), "user", None)
        allowed = accessible_email_accounts(user) if user and user.is_authenticated else queryset.none()
        super().__init__(allowed, **kwargs)

    def label_from_instance(self, obj: "EmailAccount") -> str:
        """Label a permitted sender by its email address."""
        return obj.email_address

    def _clean_bound_field(self, bound_field: forms.BoundField) -> "EmailAccount | None":
        """Allow the link to retain its actual sender after account access changes."""
        instance = getattr(bound_field.form, "instance", None)
        saved_id = getattr(instance, "email_account_id", None)
        value = bound_field.initial if self.disabled else bound_field.data
        if saved_id is not None and str(self.prepare_value(value)) == str(saved_id):
            return instance.email_account
        return super()._clean_bound_field(bound_field)
