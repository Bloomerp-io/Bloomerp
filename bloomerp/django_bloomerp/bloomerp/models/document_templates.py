from django.db import models
from django.contrib.contenttypes.models import ContentType
from bloomerp.models.core import BloomerpModel, ApplicationField
from bloomerp.models.fields import CodeField, TextEditorField, BloomerpFileField, StatusField
from django.utils.translation import gettext_lazy as _
from bloomerp.models import FileFolder
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


# ---------------------------------
# Document Template Free Variable Model
# ---------------------------------
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
        DocumentTemplateFreeVariable,
        help_text=_("A free variable is a variable that is not from a model, and can be inserted in the template at creation time.")
        ) # Many to many field of free variable, a free variable is a variable that is not from a model
    
    template_header = models.ForeignKey(
        DocumentTemplateHeader,
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
        DocumentTemplateStyling,
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
    

# ---------------------------------
# Signature Request Model
# ---------------------------------
class SignatureRequest:
    '''
    The Signature Request model can be used to request a signature from a (authenticated) user.

    Attributes:
        recipient: The recipient of the signature request.
        recipient_email: The email of the recipient (if the recipient is not provided).
        sender: The sender of the signature request.
        status: The status of the signature request.
        signed_document: The signed document of the signature request.
        signed_at: The date and time when the document was signed.

    '''
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

    
    
    
