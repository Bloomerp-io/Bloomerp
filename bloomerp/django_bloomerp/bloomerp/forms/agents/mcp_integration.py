"""Structured integration settings and unfilled secret inputs for both wizard steps."""

from __future__ import annotations

from typing import Any, ClassVar

from django import forms

from bloomerp.models.agents import MCPIntegration
from bloomerp.services.mcp.oauth import MCPAuthenticationError, validate_remote_url


class MCPIntegrationForm(forms.ModelForm):
    """Separate integration metadata from shared account authentication inputs."""

    api_key = forms.CharField(
        required=False,
        widget=forms.PasswordInput(
            render_value=False, attrs={"autocomplete": "new-password"}
        ),
        help_text="For shared API-key connections only. Personal accounts are linked later.",
    )
    oauth_client_secret = forms.CharField(
        required=False,
        widget=forms.PasswordInput(
            render_value=False, attrs={"autocomplete": "new-password"}
        ),
        help_text="Only for a shared, pre-registered confidential OAuth client.",
    )

    class Meta:
        model = MCPIntegration
        fields: ClassVar[list[str]] = [
            "name",
            "endpoint_url",
            "enabled",
            "connection_mode",
            "authentication_type",
            "oauth_client_id",
            "oauth_scopes",
        ]

    def __init__(
        self,
        *args: Any,
        allowed_fields: set[str] | None = None,
        review: bool = False,
        **kwargs: Any,
    ) -> None:
        """Apply field permissions and keep secret controls empty even during review."""
        super().__init__(*args, **kwargs)
        self.review = review
        if allowed_fields is not None:
            for name in self.Meta.fields:
                if name not in allowed_fields:
                    self.fields.pop(name, None)
        if review:
            self.fields[
                "api_key"
            ].help_text = "Leave blank to keep the authenticated key. Re-enter a key after changing the endpoint or authentication settings."
            self.fields[
                "oauth_client_secret"
            ].help_text = "Leave blank to keep the OAuth client configuration. Entering a different secret requires reconnecting."
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "input w-full")

    def clean_endpoint_url(self) -> str:
        """Require secure outbound endpoints before any authentication requests."""
        value = self.cleaned_data["endpoint_url"]
        try:
            validate_remote_url(value)
        except MCPAuthenticationError as error:
            raise forms.ValidationError(str(error)) from None
        return value

    def clean(self) -> dict[str, Any]:
        """Reject misplaced OAuth configuration and normalize requested scopes."""
        cleaned = super().clean()
        if cleaned.get("authentication_type") != "oauth":
            for field in ("oauth_client_id", "oauth_scopes"):
                if field in cleaned:
                    cleaned[field] = ""
        elif "oauth_scopes" in cleaned:
            cleaned["oauth_scopes"] = " ".join(cleaned.get("oauth_scopes", "").split())
        return cleaned

    def configuration(self) -> dict[str, Any]:
        """Return only non-secret, validated model settings suitable for wizard state."""
        return {
            name: self.cleaned_data[name]
            for name in self.Meta.fields
            if name in self.cleaned_data
        }
