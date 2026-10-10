"""Shared name validation for the file and folder rename dialogs."""

from django import forms
from django.utils.translation import gettext_lazy as _


class RenameFileForm(forms.Form):
    """Validate the new display name for either a file or a folder."""

    name = forms.CharField(max_length=100, label=_("Name"))
