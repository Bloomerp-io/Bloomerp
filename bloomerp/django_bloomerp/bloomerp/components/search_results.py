from django.apps import apps
from django.shortcuts import render
from django.http import HttpRequest, HttpResponse
from bloomerp.models import BloomerpModel, AbstractBloomerpUser
from bloomerp.utils.router import route
from bloomerp.models import Link
from bloomerp.utils.models import search_content_types_by_query, search_objects_by_content_types
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.decorators import login_required

@login_required
@route('search_results')
def search_results(request: HttpRequest) -> HttpResponse:
    '''
    Component that returns search results for a given query.
    This component is used to display search results in the search bar dropdown.
    '''
    query = request.GET.get('search_results_query', '')  # Retrieve the search query from the GET parameters
    results = []
    links = None
    not_found_response = HttpResponse('<c-ui.dropdown.item text="No results found"/>')


    if query == '':
        return not_found_response

    try:
        if query.startswith('/') and query[1] != '/':
            # In this case we want to return links for a specific model
            # Name is optional and comes after a : in the query
            sub_query = query[1:]

            name = None
            if ':' in sub_query:
                sub_query, name = sub_query.split(':')

            if '/' in sub_query:
                content_type_query = sub_query.split('/')[0]
            else:
                content_type_query = sub_query


            content_types = search_content_types_by_query(content_type_query)
            list_level_links = []

            if '/' in sub_query:
                object_query = sub_query.split('/')[-1]

                results = search_objects_by_content_types(object_query, content_types=content_types, limit=5, user=request.user)

                context = {
                    "results": results,
                    "query": query
                }

                return render(request, 'components/search_results.html', context)
                            
            else:
                for content_type in content_types:
                    links = Link.objects.filter(content_type=content_type, level='LIST')
                    if name:
                        links = links.filter(name__icontains=name)
                    
                    # If there are links for the model, add them to the list, otherwise skip
                    if links.exists():
                        list_level_links.append({
                            'model_name': content_type.model_class()._meta.verbose_name,
                            'links': links
                        })
                    
                return render(request, 'components/search_results.html', {'list_level_links': list_level_links})
        
        if query.startswith('//'):
            # In this case, we want to return app level links
            sub_query = query[2:]
            app_level_links = Link.objects.filter(level='APP', name__icontains=sub_query)
            return render(request, 'components/search_results.html', {'app_level_links': app_level_links})

        else:
            # Get all models from the app
            content_types = AbstractBloomerpUser.get_content_types_for_user(request.user)
            
            results = search_objects_by_content_types(query, content_types=content_types, limit=5, user=request.user)

            context = {
                "results": results,
                "query": query
            }

            return render(request, 'components/search_results.html', context)
    except Exception as e:
        return not_found_response
    

