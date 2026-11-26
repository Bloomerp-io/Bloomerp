"""Render the booking sender picker with a neutral label for its saved account."""

from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _


class BookingEmailAccountWidget(forms.Select):
    """Keep an unavailable selection visible without revealing the account address."""

    def optgroups(
        self, name: str, value: list[str], attrs: dict[str, Any] | None = None
    ) -> list[tuple[str | None, list[dict[str, Any]], int]]:
        """Avoid silently clearing a previously saved sender when editing another field."""
        groups = super().optgroups(name, value, attrs)
        if value and value[0] and not any(
            option["selected"] for _, options, _ in groups for option in options
        ):
            index = len(groups)
            option = self.create_option(
                name, value[0], _("Unavailable email account"), True, index, attrs=attrs
            )
            groups.append((None, [option], index))
        return groups
