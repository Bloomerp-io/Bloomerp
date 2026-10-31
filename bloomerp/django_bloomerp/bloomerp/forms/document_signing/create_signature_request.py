"""Validate the starting point and document selected for a signing request."""

import json
from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Model
from django.utils.translation import gettext_lazy as _

from bloomerp.files.access import FileAccessManager
from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.models.document_templates.document_template import DocumentTemplate
from bloomerp.models.files.file_node import FileNode
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget


class SignatureRequestSourceForm(forms.Form):
    """Accept only the supported starting points for the creation wizard."""

    source = forms.ChoiceField(
        label=_("Starting point"),
        choices=[("file", _("From file")), ("template", _("From document template"))],
        widget=forms.HiddenInput,
    )


class SignatureRequestDocumentChoiceField(forms.ModelChoiceField):
    """Give the foreign-field widget only authorized selected objects to label."""

    def prepare_value(self, value: Any) -> Model | None:
        """Resolve displayed values through the same queryset used for submission."""
        try:
            return self.to_python(value)
        except ValidationError:
            return None


class SignatureRequestDocumentForm(forms.Form):
    """Resolve the selected document through its current read permissions."""

    def __init__(
        self, *, user: AbstractBloomerpUser, source: str, **kwargs: Any
    ) -> None:
        """Offer readable PDFs or document templates for the server-selected branch."""
        super().__init__(**kwargs)
        if source == "file":
            queryset = FileAccessManager(user).get_queryset(
                FileNode.objects.filter(meta__extension="pdf")
            )
            label = _("File")
            empty_label = _("Choose a PDF file")
        elif source == "template":
            manager = UserPolicyManager(user)
            queryset = (
                manager.get_accessible_queryset(DocumentTemplate, "view")
                if manager.has_global_permission(DocumentTemplate, "view")
                else DocumentTemplate.objects.none()
            )
            label = _("Document template")
            empty_label = _("Choose a document template")
        else:
            raise ValueError("Choose a starting point before selecting a document.")
        choices_filter = Filter(
            connector="AND",
            conditions=[
                FilterCondition(
                    field_path="pk",
                    lookup_id="values_in",
                    value=[str(pk) for pk in queryset.values_list("pk", flat=True)],
                )
            ],
        )
        self.fields["document"] = SignatureRequestDocumentChoiceField(
            queryset=queryset.order_by("name", "pk"),
            label=label,
            empty_label=empty_label,
            widget=ForeignFieldWidget(
                model=queryset.model,
                attrs={
                    "aria_label": str(label),
                    "choices_filter": json.dumps(
                        [choices_filter.model_dump(mode="json")]
                    ),
                },
            ),
        )
