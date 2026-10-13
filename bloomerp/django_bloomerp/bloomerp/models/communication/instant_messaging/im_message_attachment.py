"""Provider-neutral messaging persistence."""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import IMModel


class IMMessageAttachment(IMModel):
    """Attach a stored file to a message without duplicating its binary content."""

    immutable_fields = ("message_id", "file_id")
    message = models.ForeignKey(
        "bloomerp.IMMessage", on_delete=models.CASCADE, related_name="attachments"
    )
    file = models.ForeignKey(
        "bloomerp.FileNode", on_delete=models.PROTECT, related_name="im_attachments"
    )
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=255, blank=True)
    size = models.PositiveBigIntegerField(default=0)
    provider_media_id = models.CharField(max_length=255, blank=True)

    class Meta(IMModel.Meta):
        db_table = "bloomerp_im_attachment"
        constraints = [
            models.UniqueConstraint(
                fields=["message", "file"], name="im_attachment_unique"
            )
        ]

    def clean(self) -> None:
        """Reject folders; file access itself is checked by the messaging service."""
        super().clean()
        if self.file_id and self.file.kind != "FILE":
            raise ValidationError(
                {"file": _("Only files can be attached to messages.")}
            )
