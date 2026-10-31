"""Choose the preparation role assigned to the authenticated self-signer."""

from collections.abc import Sequence
from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from bloomerp.models.document_signing import SignaturePreparationRole


class StartSelfSigningForm(forms.Form):
    """Validate a saved preparation revision and an explicit signer-role choice."""

    preparation_id = forms.UUIDField(widget=forms.HiddenInput)
    revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    role_key = forms.ChoiceField(
        label=_("Sign as"),
        widget=forms.Select(attrs={"class": "select select-sm w-full"}),
    )

    def __init__(
        self, *, roles: Sequence[SignaturePreparationRole], **kwargs: Any
    ) -> None:
        """Offer only roles from the authorized preparation, requiring a choice when ambiguous."""
        super().__init__(**kwargs)
        choices = [(role.key, role.label) for role in roles]
        self.fields["role_key"].choices = (
            choices
            if len(choices) == 1
            else [("", _("Choose a signer role")), *choices]
        )
        if len(choices) == 1:
            self.initial["role_key"] = choices[0][0]
