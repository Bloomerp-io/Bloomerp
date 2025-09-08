from bloomerp.utils.router import route
from django.shortcuts import render
from django.http import HttpResponse, HttpRequest
from bloomerp.models import ApplicationField
from bloomerp.forms.core import BloomerpModelForm
from django.forms.models import modelform_factory
import uuid
from django.contrib.auth.decorators import login_required

@login_required
@route('list_view_filter_inputs')
def list_view_filter_inputs(request:HttpRequest) -> HttpResponse:
    '''
    Returns the list view filter inputs:

    Variables:
        - application_field_id: The application field id
        - step :  Can be either 'action' or 'input'
        - action : The filter action to be performed
    '''
    # Initialize variables
    form = None
    EXCLUDED_FIELD_TYPES = ['Property', 'OneToManyField'] # Field types to exclude in the filter mechanism


    # Get the get parameters
    content_type_id = request.GET.get('content_type_id', None)
    application_field = request.GET.get('application_field_id', None)
    step = request.GET.get('step', None)

    # Some validation
    if step not in ['action', 'input','row']:
        return HttpResponse("Step is required and must be either 'action' or 'input' or 'row'", status=400)
    
    if step in ['action', 'input']:
        if not application_field:
            return HttpResponse("Application field is required", status=400)
        else:
            # Get the application field
            application_field = ApplicationField.objects.get(id=application_field)
            model = application_field.content_type.model_class()

    # Action step: renders the specific actions that can be performed on the field
    if step == 'action':
        return render(request, 'components/list_view_filter_action.html', {'application_field': application_field,'id':uuid.uuid4()})
    
    # Input step: renders the input field for the filter
    if step == 'input':
        context = {
            'application_field': application_field,
        }

        # Get the action parameter
        action = request.GET.get('action', None)
        if not action:
            return HttpResponse("Action is required", status=400)
        else:
            context['action'] = action

        # If the field is a foreign key or many to many field, get the related fields
        if application_field.field_type in ['ForeignKey', 'ManyToManyField']:
            if action == 'advanced':
                related_application_fields = ApplicationField.objects.filter(content_type=application_field.related_model).exclude(field_type__in=EXCLUDED_FIELD_TYPES)
                context['related_application_fields'] = related_application_fields

            else:
                # Create a model form that only includes the related field
                form = modelform_factory(model=model, form=BloomerpModelForm, fields=[application_field.field])(model=model, user=request.user, apply_helper=False, hide_default_fields=False)
                
                
                context['form'] = form

        return render(request, 'components/list_view_filter_input.html', context)
    
    # Row step: renders the row filter
    elif step == 'row':
        # Requires content_type_id
        if not content_type_id:
            return HttpResponse("Content type id is required", status=400)
        
        application_fields = ApplicationField.objects.filter(content_type_id=content_type_id).exclude(field_type__in=EXCLUDED_FIELD_TYPES)

        return render(request, 'components/list_view_filter_row.html', {'filter_application_fields': application_fields, 'id':uuid.uuid4()})


