from django.db import models
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.fields import CodeField
from django.utils.translation import gettext_lazy as _

# ---------------------------------
# Document Template Styling Model
# ---------------------------------
class DocumentTemplateStyling(BloomerpModel):
    avatar = None

    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'bloomerp_document_template_styling'

    name = models.CharField(max_length=100, blank=False, null=False, help_text=_("Name of the document template styling."))
    styling = CodeField(language='css', default='') #Content of the styling
    
    def __str__(self):
        return self.name

