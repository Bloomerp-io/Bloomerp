"""Show a signature request's creation and ordered recipient progress."""

from typing import Any, ClassVar

from django.db.models import QuerySet
from django.urls import reverse

from bloomerp.files.access import FileAccessManager
from bloomerp.models.document_signing import SignatureRecipient, SignatureRequest
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.views.generic.detail.base import BaseBloomerpDetailView


@router.register(
    path="status/",
    route_type="detail",
    name="Status",
    description="View the status of a signature request",
    url_name="view_status",
    models=[SignatureRequest],
)
class SignatureRequestStatusView(BaseBloomerpDetailView):
    """Render an authorized timeline without changing the request or its recipients."""

    model = SignatureRequest
    template_name = "views/document_signing/view_status.html"
    permission_fields: ClassVar[list[tuple[str, str]]] = [("datetime_created", "view")]

    def get_queryset(self) -> QuerySet[SignatureRequest]:
        """Resolve status pages only for signature requests visible to the current user."""
        return (
            UserPolicyManager(self.request.user)
            .get_accessible_queryset(SignatureRequest, BloomerpPermission.VIEW)
            .select_related("original_file", "signed_file")
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Expose readable signer progress and the signed PDF, falling back to the original."""
        context = super().get_context_data(**kwargs)
        manager = UserPolicyManager(self.request.user)
        parties: list[dict[str, Any]] = []
        if manager.has_global_permission(SignatureRecipient, BloomerpPermission.VIEW):
            recipients = (
                manager.get_accessible_queryset(
                    SignatureRecipient, BloomerpPermission.VIEW
                )
                .filter(request=self.object)
                .order_by("signing_order", "role_key", "pk")
            )
            for recipient in recipients:
                fields = set(
                    manager.get_accessible_fields_for_object(
                        recipient, BloomerpPermission.VIEW
                    ).values_list("field", flat=True)
                )
                if not {"signing_order", "status"}.issubset(fields):
                    continue
                parties.append(
                    {
                        "recipient": str(recipient),
                        "role": recipient.role_label if "role_label" in fields else "",
                        "order": recipient.signing_order,
                        "status": recipient.status,
                        "status_label": recipient.get_status_display(),
                        "signed_at": recipient.signed_at
                        if "signed_at" in fields
                        else None,
                        "declined_at": recipient.declined_at
                        if "declined_at" in fields
                        else None,
                    }
                )
        context["parties"] = parties
        context["pdf_file"] = None
        file_field = "signed_file" if self.object.signed_file_id else "original_file"
        if manager.has_access_to_object(
            self.object, BloomerpPermission.VIEW, fields=[file_field]
        ):
            file = getattr(self.object, file_field)
            if file and FileAccessManager(self.request.user).can_read_file_node(file):
                preview_url = reverse(
                    "components_preview_file", kwargs={"file_id": file.pk}
                )
                context.update(
                    pdf_file=file,
                    pdf_is_signed=file_field == "signed_file",
                    pdf_preview_url=f"{preview_url}?raw=1",
                    pdf_download_url=f"{preview_url}?download=1",
                )
        return context
