from django.db import models
from bloomerp.models.base_bloomerp_model import BloomerpModel
from django.utils.translation import gettext_lazy as _

class DocumentTemplateFreeVariable(BloomerpModel):
    avatar = None

    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'bloomerp_document_template_free_variable'

    VARIABLE_TYPE_CHOICES = [
        ('date', 'Date'),
        ('boolean', 'Boolean'),
        ('text', 'Text'),
        ('list', 'List'),
        ('integer', 'Integer'),
        ('float', 'Decimal'),
        ('model','Model')
    ]
    
    name = models.CharField(max_length=100, blank=False, null=False, help_text=_('The name of the variable.')) #Name of the free variable
    help_text = models.CharField(max_length=100, blank=True, null=True, help_text=_('Help text for the variable that will be shown upon creation.')) #Help text for the free variable
    variable_type = models.CharField(
        max_length=10, 
        choices=VARIABLE_TYPE_CHOICES, 
        blank=False, 
        null=False,
        help_text=_('The type of the variable.')
        )
    options = models.TextField(null=True, blank=True)
    required = models.BooleanField(
        null=False, 
        blank=False, 
        default=False,
        help_text=_('Signifies whether the variable is required or not.')
        )

    @property
    def slug(self):
        return self.name.replace(' ','_').lower()
    
    def __str__(self):
        return self.name
    