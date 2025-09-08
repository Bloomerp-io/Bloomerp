from bloomerp.utils.router import route
from django.shortcuts import render
from django.http import HttpResponse, HttpRequest
from bloomerp.utils.requests import parse_bool_parameter
import uuid
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from bloomerp.models import ApplicationField

@login_required
@route('datatable_and_filter')
def datatable_and_filter(request:HttpRequest) -> HttpResponse:
    content_type_id = request.GET.get('content_type_id', None)
    include_actions = parse_bool_parameter(request.GET.get('include_actions'), True)
    datatable_id = request.GET.get('datatable_id', 'datatable-' + str(uuid.uuid4()))


    content_type = ContentType.objects.get(pk=content_type_id)
    model = content_type.model_class()

    # Get the application fields
    application_fields = ApplicationField.objects.filter(content_type=content_type)


    if not content_type_id:
        return HttpResponse('content_type_id is required', status=400)
    
    context = {
        'content_type_id': content_type_id,
        'include_actions': include_actions,
        'datatable_id': datatable_id,
        'application_fields': application_fields
    }
    return render(request, 'snippets/datatable_and_filter.html', context)