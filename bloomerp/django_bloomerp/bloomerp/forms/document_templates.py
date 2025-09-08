from django import forms
from bloomerp.models import DocumentTemplate, DocumentTemplateFreeVariable
from django.apps import apps
from bloomerp.widgets.foreign_key_widget import ForeignKeyWidget

# ---------------------------------
# Free Variable Form
# ---------------------------------
class FreeVariableForm(forms.Form):
    def __init__(self, document_template: DocumentTemplate, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Set document template
        self.document_template = document_template

        # Add fields for free variables
        free_variables = document_template.free_variables.all()
        for variable in free_variables:
            variable : DocumentTemplateFreeVariable
            field_kwargs = {
                'label': f'{variable.name} (variable)',
                'required': variable.required,
                'help_text': variable.help_text,
            }
            if variable.variable_type == 'date':
                field_kwargs['widget'] = forms.DateInput(
                    attrs={'type': 'date', 'class': 'form-control'})
                field = forms.DateField(**field_kwargs)
            elif variable.variable_type == 'boolean':
                field = forms.BooleanField(**field_kwargs)

            elif variable.variable_type == 'integer':
                field = forms.IntegerField(**field_kwargs)

            elif variable.variable_type == 'float':
                field = forms.FloatField(**field_kwargs)

            elif variable.variable_type == 'text':
                field = forms.CharField(**field_kwargs)
            elif variable.variable_type == 'list':
                # Create options from choices
                options = variable.options.split(',')
                field_kwargs['choices'] = [(option, option)
                                           for option in options]

                field = forms.ChoiceField(**field_kwargs)
            elif variable.variable_type == 'model':
                # Retrieve the model
                try:
                    model = variable.options.split(',')
                    # Get the model class using the apps module without specifying app_label
                    model_class = apps.get_model(
                        app_label=model[0], model_name=model[1])

                    # Get a queryset for the model
                    queryset = model_class.objects.all()

                    # create the field
                    field = forms.ModelChoiceField(queryset=queryset)
                except:
                    # Handle the case where the model is not found
                    pass

            else:
                field = forms.CharField(**field_kwargs)

            self.fields[variable.slug] = field

        # Add hidden field for the document template
        self.fields['document_template_id'] = forms.CharField(widget=forms.HiddenInput(attrs={'value': document_template.pk}))

# ---------------------------------
# Generate Document Form
# ---------------------------------
class GenerateDocumentForm(FreeVariableForm):
    '''
    Form that is used to generate a document from a document template.
    It is not specific to any object, and can therefore be used outside of the detail-view.
    '''
    instance = None
    persist = False

    # Add a field for persisting the document
    save_file = forms.BooleanField(
        label='Save document',
        required=False,
        help_text='Check this box to save the document to the database')
    

    def __init__(
            self, 
            document_template: DocumentTemplate,
            add_persist_field : bool = True,
            *args, **kwargs):
        super().__init__(document_template, *args, **kwargs)

        if document_template.model_variable:
            related_model = document_template.model_variable.model_class()
            field = forms.ModelChoiceField(
                queryset=related_model.objects.all(), widget=ForeignKeyWidget(related_model))
            self.fields['generate_document_for'] = field

            self.fields['generate_document_for'].label = f'Generate document for {related_model._meta.verbose_name}'

            # Set position of the field to the top
            self.order_fields(['save_file','generate_document_for'])

        if not add_persist_field:
            self.fields.pop('save_file')

    def clean(self):
        cleaned_data = super().clean()

        # Check if the generate_document_for field is present
        if 'generate_document_for' in cleaned_data:
            self.instance = cleaned_data['generate_document_for']    

        # Check if the save_file field is present
        if 'save_file' in cleaned_data:
            self.persist = cleaned_data['save_file']

        return cleaned_data
    
    def has_persist_field(self) -> bool:
        '''Returns whether the form has a persist field or not.'''
        if self.fields.get('save_file',False):
            return True
        else:
            return False
    
    