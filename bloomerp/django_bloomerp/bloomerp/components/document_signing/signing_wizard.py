"""Open the reusable signing wizard for an existing PDF."""

from typing import Any

from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView

from bloomerp.document_signing.access import can_create_request
from bloomerp.files.access import FileAccessManager
from bloomerp.models.files.file_node import FileNode
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.signing_wizard_mixin import SigningWizardMixin


@router.register(
    path="components/document_signing/wizard/<uuid:file_id>/",
    url_name="components_document_signing_wizard",
)
class SigningWizardComponent(SigningWizardMixin, BaseBloomerpView, TemplateView):
    """Reuse preparation and send/self-sign steps from the file object's Sign action."""

    def setup(self, request: HttpRequest, *args: Any, **kwargs: Any) -> None:
        """Keep each PDF's wizard progress in its own session namespace."""
        self.session_key = f"document_signing_wizard_{kwargs['file_id']}"
        super().setup(request, *args, **kwargs)

    def has_permission(self) -> bool:
        """Require the same request-creation capability as the model create wizard."""
        return can_create_request(UserPolicyManager(self.request.user))

    def get_signing_file(self) -> FileNode:
        """Resolve only a currently readable PDF for the supplied route identifier."""
        return get_object_or_404(
            FileAccessManager(self.request.user).get_queryset(
                FileNode.objects.filter(meta__extension="pdf")
            ),
            pk=self.kwargs["file_id"],
        )
