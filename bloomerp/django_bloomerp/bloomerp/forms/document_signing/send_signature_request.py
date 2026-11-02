"""Fields for assigning concrete email recipients to generic signing roles."""

from collections.abc import Sequence
from email.utils import getaddresses
from typing import Any

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from bloomerp.form_fields.text_editor_field import TextEditorFormField
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.models.document_signing import (
    SignatureLayoutRole,
    SignaturePreparationRole,
)
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.services.email_composer_services import accessible_email_accounts
from bloomerp.utils.rich_text import sanitize_html


class SignatureDispatchForm(forms.Form):
    """Validate the stable submission key and expected signing source revision."""

    submission_id = forms.UUIDField(widget=forms.HiddenInput)
    source_revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class SignatureRequestEmailForm(forms.Form):
    """Share the invitation message and accessible sending account between delivery flows."""

    sender = forms.ModelChoiceField(
        queryset=EmailAccount.objects.none(),
        required=True,
        label=_("From email account"),
        empty_label=_("Choose an email account"),
        widget=forms.Select(
            attrs={"class": "select select-sm w-full", "data-email-sender": ""}
        ),
    )
    content = TextEditorFormField(required=False, label=_("Email content"))

    def __init__(self, *, user: AbstractBloomerpUser, **kwargs: Any) -> None:
        """Limit sending accounts and configure the shared invitation editor."""
        super().__init__(**kwargs)
        self.user = user
        self.fields["sender"].queryset = accessible_email_accounts(user).filter(
            status=EmailAccount.Status.ACTIVE
        )
        self.fields["content"].widget.attrs.update(
            {
                "has_border": False,
                "placeholder": _("Write an optional message to your recipients…"),
            }
        )

    def clean(self) -> dict[str, Any]:
        """Sanitize the message before it is stored or delivered."""
        data = super().clean()
        data["content"] = sanitize_html(data.get("content") or "")
        return data


class SendSignatureRequestForm(SignatureRequestEmailForm):
    """Assign recipients and optionally deliver invitations while creating their request."""

    send_email = forms.BooleanField(
        required=False,
        initial=True,
        label=_("Send email"),
        widget=forms.CheckboxInput(
            attrs={"class": "checkbox checkbox-primary", "data-send-email": ""}
        ),
    )
    valid_until = forms.DateTimeField(
        required=False,
        label=_("Valid until"),
        help_text=_("Leave empty for no expiry."),
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={"type": "datetime-local", "class": "input input-sm w-full"},
        ),
    )

    def __init__(
        self,
        *,
        user: AbstractBloomerpUser,
        roles: Sequence[SignatureLayoutRole | SignaturePreparationRole],
        assign_only: bool = False,
        **kwargs: Any,
    ) -> None:
        """Build the role pickers, optionally limiting the form to recipient assignment."""
        super().__init__(user=user, **kwargs)
        self.assign_only = assign_only
        self.fields["sender"].required = False
        if assign_only:
            for name in ("sender", "send_email", "content", "valid_until"):
                del self.fields[name]
        self.assignments: dict[str, dict[str, Any]] = {}
        self.recipient_names: list[tuple[str, str]] = []
        self.recipient_fields: list[tuple[forms.BoundField, forms.BoundField]] = []
        for role in roles:
            name = f"recipient_{role.key}"
            self.fields[name] = forms.CharField(
                required=False,
                label=role.label,
                widget=forms.TextInput(
                    attrs={
                        "data-recipient-input": "",
                        "aria-label": str(_("Recipient for %(role)s"))
                        % {"role": role.label},
                        "autocomplete": "off",
                        "placeholder": "name@example.com",
                    }
                ),
            )
            user_name = f"recipient_users_{role.key}"
            self.fields[user_name] = forms.JSONField(
                required=False,
                initial=[],
                widget=forms.HiddenInput(attrs={"data-recipient-users": ""}),
            )
            self.recipient_names.append((name, user_name))
            self.recipient_fields.append((self[name], self[user_name]))

    def clean(self) -> dict[str, Any]:
        """Validate role assignments and require external email delivery only in the sending flow."""
        data = super().clean()
        manager = UserPolicyManager(self.user)
        external = False
        internal_users: list[tuple[str, AbstractBloomerpUser]] = []
        for name, user_name in self.recipient_names:
            raw = data.get(name, "").strip()
            identifiers = data.get(user_name) or []
            if (
                not isinstance(identifiers, list)
                or len(identifiers) > 1
                or any(not isinstance(identifier, str) for identifier in identifiers)
            ):
                self.add_error(name, _("Choose one recipient for this role."))
                continue
            if identifiers:
                person = self.resolve_internal_user(identifiers[0], manager)
                if person is None or (
                    raw and raw.casefold() != person.email.casefold()
                ):
                    self.add_error(
                        name,
                        _(
                            "The selected user is unavailable or does not match this address."
                        ),
                    )
                else:
                    internal_users.append((name, person))
                    self.assignments[name.removeprefix("recipient_")] = {
                        "user": person,
                        "email": person.email,
                        "name": (person.get_full_name() or person.email or str(person))[
                            :255
                        ],
                    }
                continue
            addresses = getaddresses([raw.replace(";", ",")])
            try:
                if len(addresses) != 1:
                    raise ValidationError(_("Choose one recipient for this role."))
                validate_email(addresses[0][1])
            except ValidationError as error:
                self.add_error(name, error)
                continue
            data[name] = addresses[0][1]
            self.assignments[name.removeprefix("recipient_")] = {
                "user": None,
                "email": addresses[0][1],
                "name": (addresses[0][0] or addresses[0][1])[:255],
            }
            external = True
        data["send_email"] = not self.assign_only and (
            external or bool(data.get("send_email"))
        )
        if data["send_email"]:
            if not data.get("sender") and "sender" not in self.errors:
                self.add_error("sender", _("Choose an email account to send email."))
            for name, person in internal_users:
                if not person.email:
                    self.add_error(
                        name, _("This user needs an email address to receive email.")
                    )
        if data.get("valid_until") and data["valid_until"] <= timezone.now():
            self.add_error("valid_until", _("Choose an expiry in the future."))
        return data

    def resolve_internal_user(
        self, identifier: str, manager: UserPolicyManager
    ) -> AbstractBloomerpUser | None:
        """Resolve only active accounts whose rows and email fields the sender may read."""
        model = get_user_model()
        if not manager.has_global_permission(model, "view"):
            return None
        try:
            person = (
                manager.get_accessible_queryset(model, "view")
                .filter(pk=identifier, is_active=True)
                .first()
            )
        except (ValueError, ValidationError):
            return None
        if person is not None and manager.has_access_to_object(
            person, "view", fields=["email"]
        ):
            return person
        return None
