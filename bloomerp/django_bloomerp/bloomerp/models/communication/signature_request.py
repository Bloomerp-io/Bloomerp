from django.db import models
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.fields import BloomerpFileField, StatusField
from django.utils.translation import gettext_lazy as _
from django.conf import settings


class SignatureRequest:
    """"
    The Signature Request model can be used to request a signature from a (authenticated) user.

    Attributes:
        recipient: The recipient of the signature request.
        recipient_email: The email of the recipient (if the recipient is not provided).
        sender: The sender of the signature request.
        status: The status of the signature request.
        signed_document: The signed document of the signature request.
        signed_at: The date and time when the document was signed.
    """
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'bloomerp_signature_request'


    avatar = None

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        help_text=_("Recipient of the signature request."),
        related_name='incoming_signature_requests',
        null=True,
        blank=True
        ) # Foreign key to the recipient
    
    recipient_email = models.EmailField(
        help_text=_("Email of the recipient (if recipient is not provided)."),
        null=True,
        blank=True
        ) # Email of the recipient


    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        help_text=_("Sender of the signature request.")
        ) # Foreign key to the sender
    
    status = StatusField(
        default='pending',
        help_text=_("Status of the signature request."),
        colored_choices=[
            ('pending', 'Pending', '#ffcc00'),
            ('processing', 'Processing', '#007bff'),
            ('completed', 'Completed', '#28a745'),
            ('cancelled', 'Cancelled', '#dc3545'),
        ]
    )
    
    signed_document = BloomerpFileField()
    
    signed_at = models.DateTimeField(
        help_text=_("Date and time when the document was signed."),
        blank=True,
        null=True
        ) # Date and time when the document was signed
    
    def __str__(self):
        return f'{self.document_template.name} - {self.recipient.get_full_name()}'

    
    
    
