from django.db import models
from django.contrib.contenttypes.models import ContentType
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.fields import CodeField, TextEditorField, BloomerpFileField, StatusField
from django.utils.translation import gettext_lazy as _
from bloomerp.models.files.file_folder import FileFolder
from django.contrib.auth import get_user_model
from django.conf import settings


# ---------------------------------
# Document Template Model
# ---------------------------------
class DocumentTemplateHeader(BloomerpModel):
    avatar = None

    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'bloomerp_document_template_header'

    name = models.CharField(
        max_length=100,
        blank=False,
        null=False, 
        help_text=_("Name of the template header.")) #Name of the document template header
    header = models.ImageField(
        help_text=_("Image of the header."),
        upload_to='document_templates/headers',
    ) 
    margin_top = models.FloatField(default=0.5, help_text=_("Top margin of the header in inches."))
    margin_bottom = models.FloatField(default=0.0, help_text=_("Bottom margin of the header in inches."))
    margin_left = models.FloatField(default=1.0, help_text=_("Left margin of the header in inches."))
    margin_right = models.FloatField(default=1.0, help_text=_("Right margin of the header in inches."))

    height = models.FloatField(default=1.0, help_text=_("Height of the header in inches."))
    
    def __str__(self):
        return self.name
