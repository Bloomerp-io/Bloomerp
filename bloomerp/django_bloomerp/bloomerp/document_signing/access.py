"""Resolve document-signing permissions through Bloomerp row, field, and file access."""

from uuid import UUID

from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from bloomerp.files.access import FileAccessManager
from bloomerp.models.document_signing import (
    SignatureLayout,
    SignatureLayoutField,
    SignatureLayoutRole,
    SignaturePreparation,
    SignaturePreparationField,
    SignaturePreparationRole,
    SignatureRecipient,
    SignatureRequest,
    SignatureRequestField,
)
from bloomerp.models.document_signing.base import SigningModel
from bloomerp.models.document_templates.document_template import DocumentTemplate
from bloomerp.models.files.file_node import FileNode
from bloomerp.models.files.file_reference import FileReference
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager

LAYOUT_FIELDS = ("name", "revision", "preview_file")


LAYOUT_ROLE_FIELDS = ("layout", "key", "label", "default_signing_order")


LAYOUT_PLACEMENT_FIELDS = (
    "layout",
    "role",
    "key",
    "field_type",
    "required",
    "page_number",
    "x",
    "y",
    "width",
    "height",
    "settings",
)

PREPARATION_FIELDS = ("title", "revision", "original_file", "source_layout")


PREPARATION_ROLE_FIELDS = ("preparation", "key", "label", "signing_order")


PREPARATION_PLACEMENT_FIELDS = (
    "preparation",
    "role",
    "key",
    "field_type",
    "required",
    "page_number",
    "x",
    "y",
    "width",
    "height",
    "settings",
)

REQUEST_FIELDS = (
    "title",
    "status",
    "original_file",
    "original_sha256",
    "signed_file",
    "signed_sha256",
    "source_preparation",
    "source_preparation_revision",
    "sent_at",
    "expires_at",
    "completed_at",
)

DISPATCH_FIELDS = (
    *REQUEST_FIELDS,
    "source_layout",
    "source_layout_name",
    "source_layout_revision",
    "email_account",
    "email_content",
)
INVITATION_SALT = "bloomerp.document-signing.invitation.v1"


RECIPIENT_FIELDS = (
    "request",
    "user",
    "role_key",
    "role_label",
    "name",
    "email",
    "signing_order",
    "status",
)


REQUEST_FIELD_FIELDS = (
    "request",
    "recipient",
    "key",
    "field_type",
    "required",
    "page_number",
    "x",
    "y",
    "width",
    "height",
    "settings",
    "value",
    "filled_at",
)


def get_signing_document_templates(
    file: FileNode, manager: UserPolicyManager
) -> list[DocumentTemplate]:
    """Resolve readable record-level template references without choosing an ambiguous origin."""
    references = file.get_references(models=[DocumentTemplate]).filter(
        application_field__isnull=True, occurrence_id__isnull=True
    )
    template_ids = []
    for value in references.values_list("object_id", flat=True):
        try:
            template_ids.append(DocumentTemplate._meta.pk.to_python(value))
        except (DjangoValidationError, ValueError, TypeError):
            continue
    templates = (
        manager.get_accessible_queryset(DocumentTemplate, BloomerpPermission.VIEW)
        .filter(pk__in=template_ids)
        .order_by("name", "pk")
    )
    return [
        template
        for template in templates
        if manager.has_access_to_object(
            template, BloomerpPermission.VIEW, fields=["default_signature_layout"]
        )
    ]


def can_save_signing_default(
    template: DocumentTemplate, manager: UserPolicyManager
) -> bool:
    """Expose saving only when the template link and new layout records are writable."""
    if not manager.has_access_to_object(
        template, BloomerpPermission.CHANGE, fields=["default_signature_layout"]
    ):
        return False
    for model, fields in (
        (SignatureLayout, LAYOUT_FIELDS),
        (SignatureLayoutRole, LAYOUT_ROLE_FIELDS),
        (SignatureLayoutField, LAYOUT_PLACEMENT_FIELDS),
    ):
        for permission in (BloomerpPermission.ADD, BloomerpPermission.VIEW):
            if not manager.has_global_permission(model, permission):
                return False
            allowed = set(
                manager.get_accessible_fields(model, permission).values_list(
                    "field", flat=True
                )
            )
            if not set(fields).issubset(allowed):
                return False
    return True


def get_signing_layout_revisions(
    template: DocumentTemplate, manager: UserPolicyManager
) -> list[SignatureLayout]:
    """List readable revisions belonging to this template, including an unlinked legacy default."""
    layouts = (
        manager.get_accessible_queryset(SignatureLayout, BloomerpPermission.VIEW)
        .filter(
            Q(document_template=template)
            | Q(pk=template.default_signature_layout_id, document_template__isnull=True)
        )
        .order_by("-revision", "-datetime_created", "pk")
    )
    return [
        layout
        for layout in layouts
        if can_signing_access(layout, manager, BloomerpPermission.VIEW, LAYOUT_FIELDS)
    ]


def can_signing_access(
    instance: SigningModel,
    manager: UserPolicyManager,
    permission: BloomerpPermission,
    fields: tuple[str, ...],
) -> bool:
    """Evaluate the shared global, row, and field rules for one signing record."""
    return manager.has_access_to_object(instance, permission, fields=list(fields))


def require_signing_access(
    instance: SigningModel,
    manager: UserPolicyManager,
    permission: BloomerpPermission,
    fields: tuple[str, ...],
) -> None:
    """Enforce global, row, and row-sensitive field permissions for a signing record."""
    if not can_signing_access(instance, manager, permission, fields):
        raise PermissionDenied("You do not have access to all signing layout fields.")


def can_prepare(file: FileNode, manager: UserPolicyManager) -> bool:
    """Check whether the actor may read the file used for document preparation."""
    return FileAccessManager(manager.user).can_read_file_node(file)


def can_generate_signing_template(
    template: DocumentTemplate, manager: UserPolicyManager
) -> bool:
    """Require readable generation settings and permission to persist a PDF and its references."""
    return manager.has_access_to_object(
        template,
        BloomerpPermission.VIEW,
        fields=[
            "template",
            "free_variables",
            "content_types",
            "template_header",
            "footer",
            "page_orientation",
            "page_size",
            "page_margin",
            "include_page_numbers",
            "style_sets",
            "custom_styling",
        ],
    ) and all(
        manager.has_global_permission(model, BloomerpPermission.ADD)
        for model in (FileNode, FileReference)
    )


def can_use_layout(layout: SignatureLayout | None, manager: UserPolicyManager) -> bool:
    """Check whether a saved draft may refer to the layout's readable name and revision."""
    return layout is not None and can_signing_access(
        layout, manager, BloomerpPermission.VIEW, ("name", "revision")
    )


def can_save_preparation(
    manager: UserPolicyManager, permission: BloomerpPermission | None = None
) -> bool:
    """Check the requested draft operation or the full capability used by the builder UI."""
    if permission is not None:
        return manager.has_global_permission(SignaturePreparation, permission)
    return all(
        manager.has_global_permission(model, operation)
        for model in (
            SignaturePreparation,
            SignaturePreparationRole,
            SignaturePreparationField,
        )
        for operation in (
            BloomerpPermission.VIEW,
            BloomerpPermission.ADD,
            BloomerpPermission.CHANGE,
        )
    )


def can_create_request(manager: UserPolicyManager) -> bool:
    """Check creation capability for a request and its concrete recipients and fields."""
    return all(
        manager.has_global_permission(model, BloomerpPermission.ADD)
        for model in (SignatureRequest, SignatureRecipient, SignatureRequestField)
    )


def require_create_request(manager: UserPolicyManager) -> None:
    """Enforce the same request-creation capability exposed to callers."""
    if not can_create_request(manager):
        raise PermissionDenied("You cannot create signing requests.")


def can_manage_signing_request(
    signing_request: SignatureRequest, manager: UserPolicyManager
) -> bool:
    """Require readable content and delivery-change permissions for an available request."""
    return (
        manager.user.is_authenticated
        and signing_request.status
        in {SignatureRequest.Status.DRAFT, SignatureRequest.Status.SENT}
        and not (
            signing_request.expires_at and signing_request.expires_at <= timezone.now()
        )
        and can_signing_access(
            signing_request, manager, BloomerpPermission.VIEW, DISPATCH_FIELDS
        )
        and can_signing_access(
            signing_request,
            manager,
            BloomerpPermission.CHANGE,
            ("email_account", "email_content"),
        )
        and can_prepare(signing_request.original_file, manager)
    )


def can_share_signing_request(
    signing_request: SignatureRequest, manager: UserPolicyManager
) -> bool:
    """Allow request managers to distribute links only for assigned, open signing requests."""
    return (
        can_manage_signing_request(signing_request, manager)
        and signing_request.status == SignatureRequest.Status.SENT
        and signing_request.recipients.filter(status__in=["pending", "viewed"]).exists()
        and all(
            can_signing_access(
                recipient, manager, BloomerpPermission.VIEW, RECIPIENT_FIELDS
            )
            for recipient in signing_request.recipients.all()
        )
    )


def can_send_signing_request(
    signing_request: SignatureRequest, manager: UserPolicyManager
) -> bool:
    """Allow recipient assignment on a saved draft or delivery to existing unsent recipients."""
    if signing_request.status == SignatureRequest.Status.DRAFT:
        return can_assign_signing_request(signing_request, manager)
    if not can_share_signing_request(signing_request, manager):
        return False
    recipients = [
        recipient
        for recipient in signing_request.recipients.filter(
            status__in=["pending", "viewed"]
        )
        if recipient.email_delivery.get("status")
        not in {"accepted", "unconfirmed", "sending"}
    ]
    return bool(recipients) and all(
        bool(recipient.email)
        and can_signing_access(
            recipient, manager, BloomerpPermission.CHANGE, ("email_delivery",)
        )
        for recipient in recipients
    )


def can_assign_signing_request(
    signing_request: SignatureRequest, manager: UserPolicyManager
) -> bool:
    """Allow a request manager to assign the prepared roles of an unassigned draft."""
    return (
        signing_request.status == SignatureRequest.Status.DRAFT
        and can_manage_signing_request(signing_request, manager)
        and signing_request.source_preparation_id is not None
        and can_create_request(manager)
        and not signing_request.recipients.exists()
    )


def can_download(recipient: SignatureRecipient, manager: UserPolicyManager) -> bool:
    """Check signer ownership and current row, field, and file access to a signing PDF."""
    return (
        recipient.user_id is not None
        and recipient.user_id == manager.user.pk
        and can_signing_access(
            recipient.request, manager, BloomerpPermission.VIEW, REQUEST_FIELDS
        )
        and can_signing_access(
            recipient, manager, BloomerpPermission.VIEW, RECIPIENT_FIELDS
        )
        and can_prepare(recipient.request.original_file, manager)
    )


def require_download(recipient: SignatureRecipient, manager: UserPolicyManager) -> None:
    """Require the same authenticated PDF access used by download availability checks."""
    if not can_download(recipient, manager):
        raise PermissionDenied("You cannot read this signing request.")


def can_sign(recipient: SignatureRecipient, manager: UserPolicyManager) -> bool:
    """Check ownership and write access for the recipient's consent and assigned values."""
    if not can_download(recipient, manager):
        return False
    if not can_signing_access(
        recipient,
        manager,
        BloomerpPermission.CHANGE,
        ("status", "consent_text", "consented_at", "signed_at"),
    ):
        return False
    return all(
        can_signing_access(
            field, manager, BloomerpPermission.VIEW, REQUEST_FIELD_FIELDS
        )
        and can_signing_access(
            field, manager, BloomerpPermission.CHANGE, ("value", "filled_at")
        )
        for field in recipient.fields.all()
    )


def require_sign(recipient: SignatureRecipient, manager: UserPolicyManager) -> None:
    """Enforce signer ownership and the shared consent/field-write capability."""
    if not can_sign(recipient, manager):
        raise PermissionDenied("You cannot sign this request.")


def get_request_signing_recipient(
    manager: UserPolicyManager, signing_request: SignatureRequest
) -> SignatureRecipient | None:
    """Find the caller's next open role whose signing order and permissions allow signing."""
    if (
        not manager.user.is_authenticated
        or signing_request.status != SignatureRequest.Status.SENT
        or (signing_request.expires_at and signing_request.expires_at <= timezone.now())
    ):
        return None
    recipients = signing_request.recipients.filter(
        user_id=manager.user.pk,
        status__in=[
            SignatureRecipient.Status.PENDING,
            SignatureRecipient.Status.VIEWED,
        ],
    ).select_related("request__original_file")
    for recipient in recipients:
        earlier_pending = (
            signing_request.recipients.filter(signing_order__lt=recipient.signing_order)
            .exclude(status=SignatureRecipient.Status.SIGNED)
            .exists()
        )
        if not earlier_pending and can_sign(recipient, manager):
            return recipient
    return None


def get_signing_preparation(
    manager: UserPolicyManager,
    file_id: str,
    preparation_id: str | UUID,
) -> SignaturePreparation:
    """Resolve one readable preparation and PDF without allowing a mismatched file identifier."""
    try:
        preparation = get_object_or_404(
            manager.get_accessible_queryset(
                SignaturePreparation, BloomerpPermission.VIEW
            ).select_related("original_file", "source_layout"),
            pk=preparation_id,
            original_file_id=file_id,
        )
    except (DjangoValidationError, ValueError, TypeError) as error:
        raise ValidationError("Choose a valid signing preparation.") from error
    require_signing_access(
        preparation, manager, BloomerpPermission.VIEW, PREPARATION_FIELDS
    )
    if not can_prepare(preparation.original_file, manager):
        raise PermissionDenied("You cannot read this PDF.")
    if preparation.original_file.metadata.extension != "pdf":
        raise ValidationError("Choose a PDF document.")
    return preparation


def get_signing_recipient(
    manager: UserPolicyManager, recipient_id: str | UUID
) -> SignatureRecipient:
    """Require an explicit signer identity, current PDF access, and row/field permissions."""
    try:
        recipient = get_object_or_404(
            SignatureRecipient.objects.select_related(
                "request__original_file", "request__signed_file"
            ),
            pk=recipient_id,
            user_id=manager.user.pk,
        )
    except (DjangoValidationError, ValueError, TypeError) as error:
        raise ValidationError("Choose a valid signing recipient.") from error
    require_download(recipient, manager)
    return recipient


def signing_invitation(recipient: SignatureRecipient) -> str:
    """Issue a signed capability bound to one immutable recipient and original PDF digest."""
    return signing.dumps(
        {"recipient": str(recipient.pk), "digest": recipient.request.original_sha256},
        salt=INVITATION_SALT,
    )


def get_invited_recipient(
    token: str, request_id: UUID | None = None
) -> SignatureRecipient:
    """Validate the emailed signer and expiry, optionally bound to a request's detail URL."""
    try:
        payload = signing.loads(token, salt=INVITATION_SALT)
        if not isinstance(payload, dict):
            raise TypeError("Invalid invitation payload.")
        recipient = get_object_or_404(
            SignatureRecipient.objects.select_related(
                "request__original_file", "request__signed_file", "request__created_by"
            ),
            pk=UUID(payload["recipient"]),
        )
    except (signing.BadSignature, ValueError, TypeError, KeyError) as error:
        raise PermissionDenied("This signing link is invalid.") from error
    request = recipient.request
    if request_id is not None and str(request.pk) != str(request_id):
        raise PermissionDenied("This signing link belongs to another request.")
    if request.original_sha256 != payload.get("digest"):
        raise PermissionDenied("This signing link is invalid.")
    if request.status not in {"sent", "completed"}:
        raise PermissionDenied("This signing request is no longer available.")
    if request.expires_at and request.expires_at <= timezone.now():
        raise PermissionDenied("This signing request has expired.")
    return recipient
