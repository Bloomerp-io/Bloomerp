from bloomerp.utils.router import route
from django.shortcuts import render
from django.http import HttpResponse, HttpRequest
from bloomerp.models import ApplicationField
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType

@login_required
@route('list_view_filter')
def list_view_filter(request:HttpRequest) -> HttpResponse:
    '''
    Renders list view filter component.

    Variables:
        - content_type_id: The content type id of the model to be rendered in the data table
        - target : The target of the data table
    '''
    content_type_id = request.GET.get('content_type_id', None)
    target = request.GET.get('target', None)
    include_actions = request.GET.get('data_table_include_actions', False) # Actions will be rendered to the right of the table for each row
    user = request.user

    if not content_type_id:
        return HttpResponse("Content type id is required", status=400)
    if not target:
        return HttpResponse("Target is required", status=400)
    else:
        target = "#" + target

    # Some logic for permissions here based on content_type_id
    model = ContentType.objects.get(id=content_type_id).model_class()
    if not user.has_perm(f'{model._meta.app_label}.view_{model._meta.model_name}'):
        return HttpResponse('User does not have permission to view this data table')


    # Get the application fields for the content type
    application_fields = ApplicationField.objects.filter(content_type_id=content_type_id).exclude(field_type='Property')
    

    context = {
        'application_fields': application_fields,
        'target': target,
        'content_type_id': content_type_id,
        'include_actions': include_actions
    }
    return render(request, 'snippets/list_view_filter.html', context)