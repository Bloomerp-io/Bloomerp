from bloomerp.utils.router import route
from django.shortcuts import render
from django.http import HttpResponse, HttpRequest
from django.contrib.contenttypes.models import ContentType
from bloomerp.models import BloomerpModel
from bloomerp.utils.models import string_search
from django.contrib.auth.decorators import login_required

@login_required
@route('fk_search_results')
def fk_search_results(request:HttpRequest) -> HttpResponse:
    '''
    Component that returns search results for a given query.
    This component is used for foreign key or many to many fields.
    '''

    Model : BloomerpModel = ContentType.objects.get_for_id(request.GET.get('content_type_id')).model_class()
    query = request.GET.get('fk_search_results_query')
    field_name = request.GET.get('field_name')
    search_type = request.GET.get('search_type','fk')

    if search_type not in ['fk','m2m']:
        pass


    if query:
        # Check if the model has a string_search method, it is inherited from BloomerpModel
        if not hasattr(Model, 'string_search'):
            # Add the string_search method to the model
            Model.string_search = classmethod(string_search)
        
        context = {
            'objects': Model.string_search(query)[:5]
        }
    else:
        context = {
            'objects': Model.objects.all()[:5]
        }

    context['field_name'] = field_name
    context['type'] = search_type

    return render(request, 'components/fk_search_results.html', context)