from django.db import models
from django.contrib.contenttypes.models import ContentType
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.fields import TextEditorField
from django.utils.translation import gettext_lazy as _
from bloomerp.models.files.file_folder import FileFolder
from django.conf import settings


# ---------------------------------
# Document Template Model
# ---------------------------------
class DocumentTemplate(BloomerpModel):
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'bloomerp_document_template'

    avatar = None

    ORIENTATION_CHOICES = [
        ('portrait', 'Portrait'),
        ('landscape', 'Landscape')
    ]

    PAGE_SIZE_CHOICES = [
        ('A4', 'A4'),
        ('letter', 'Letter'),
        ('A3', 'A3')
    ]

    name = models.CharField(
        max_length=100,
        help_text=_("Name of the document template.")
        ) #Name of the document template
    template = TextEditorField(
        default='Hello world',
        help_text=_("Content of the template, including the variables.")
        ) # Content of the template, including the variables
    model_variable = models.ForeignKey(
        ContentType, 
        on_delete=models.CASCADE,
        help_text=_("Model variable of the document template. Can be used to parse objects from the model into the template."),
        null=True,
        blank=True
        ) # Many to many field to Content Type
    free_variables = models.ManyToManyField(
        "DocumentTemplateFreeVariable",
        help_text=_("A free variable is a variable that is not from a model, and can be inserted in the template at creation time.")
        ) # Many to many field of free variable, a free variable is a variable that is not from a model
    
    template_header = models.ForeignKey(
        "DocumentTemplateHeader",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_("Header of the document template.")
        ) #Foreign key to the document template header
    footer = models.TextField(
        help_text=_("Footer content of the document template."),
        blank=True,
        null=True
        )
    styling = models.ForeignKey(
        "DocumentTemplateStyling",
        on_delete=models.SET_NULL,
        null=True, 
        blank=True,
        help_text=_("Styling of the document template.")
        ) # Foreign key to the document template styling
    page_orientation = models.CharField(
        max_length=10,
        default='portrait',
        help_text=_("Orientation of the document template."),
        choices=ORIENTATION_CHOICES
        ) # Orientation of the document template
    page_size = models.CharField(
        max_length=10,
        default='A4',
        help_text=_("Size of the document template."),
        choices=PAGE_SIZE_CHOICES
        ) 
    page_margin = models.FloatField(
        default=1.0,
        help_text=_("Margin of the document template in inches.")
        ) # Margin of the document template in inches
    include_page_numbers = models.BooleanField(
        default=True,
        help_text=_("Signifies whether the page numbers are included or not.")
        ) 

    save_to_folder = models.ForeignKey(
        to = FileFolder,
        null=True,
        blank=True,
        help_text=_('Signifies to which folder a file generated from the template needs to be saved upon creation.'),
        on_delete=models.SET_NULL
    )


    form_layout = {
        "General information" : ['name', 'model_variable', 'free_variables'],
        "Template content" : ['template'],
        "Styling" : ['styling', 'template_header','footer', 'page_orientation','page_size','page_margin','include_page_numbers'],
        "Saving" : ['save_to_folder']
    }


    def __str__(self):
        return self.name

    allow_string_search = True
    string_search_fields = ['name']

    def get_related_content_types(model):
        related_content_types = [ContentType.objects.get_for_model(model)]
        return related_content_types

    @property
    def application_fields(self):
        '''
        Returns a queryset of ApplicationField that are related to the model variable of the document template.
        '''
        if self.model_variable is None:
            return ApplicationField.objects.none()
        else:
            qs = ApplicationField.objects.filter(content_type=self.model_variable)
            return qs
    
    def get_variables(self) -> list[(str, str, str)]:
        '''
        Returns a list of tuples with the name and type of the variables in the template.

        The tuple is in the format (name, type, description)
        '''
        variables = []

        # Add the application fields
        for field in self.application_fields:
            variables.append(('object.'+field.field, field.field_type, 'Object field'))

        # Add the free variables
        for variable in self.free_variables.all():
            variables.append((variable.slug, variable.variable_type, 'Free variable'))

        return variables

    @staticmethod
    def get_standard_documents_for_instance(instance):
        content_type = ContentType.objects.get_for_model(instance)
        return DocumentTemplate.objects.filter(model_variable=content_type, standard_document=True)
    
