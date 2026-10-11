from django.db import models
from bloomerp.models import BloomerpModel
from bloomerp.model_fields.code_field import CodeField
from django.utils.translation import gettext_lazy as _


# ---------------------------------
# Document Template Styling Model
# ---------------------------------
class DocumentTemplateStyling(BloomerpModel):
    avatar = None

    class Meta(BloomerpModel.Meta):
        verbose_name = _("Document Template Styling")
        verbose_name_plural = _("Document Template Stylings")
        managed = True
        db_table = "bloomerp_document_template_styling"

    name = models.CharField(
        max_length=100,
        blank=False,
        null=False,
        help_text=_("Name of the document template styling."),
        verbose_name=_("Name"),
    )
    styling = CodeField(
        language="css", default="", verbose_name=_("Styling")
    )  # Content of the styling

    def __str__(self):
        return self.name
