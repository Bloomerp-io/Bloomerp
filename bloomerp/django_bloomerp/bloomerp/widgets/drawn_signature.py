"""Render an ink capture control backed by a JSON value rather than typed text."""

from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _


class DrawnSignatureWidget(forms.HiddenInput):
    """Keep validated stroke data in the form while a component owns its drawing pad."""

    template_name = "widgets/drawn_signature.html"

    def get_context(
        self, name: str, value: Any, attrs: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Expose the field label and requirement to its accessible drawing control."""
        context = super().get_context(name, value, attrs)
        context["widget"]["attrs"]["data-signature-value"] = ""
        context["signature_label"] = self.attrs.get("aria-label", str(_("Signature")))
        context["signature_required"] = self.is_required
        return context
