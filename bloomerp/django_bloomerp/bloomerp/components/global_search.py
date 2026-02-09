from django.shortcuts import render
from django.http import HttpRequest, HttpResponse
from bloomerp.router import router
from django.contrib.auth.decorators import login_required

@router.register(path='components/global_search/', name='components_global_search')
@login_required
def global_search(request: HttpRequest) -> HttpResponse:
    '''
    Component that returns search results for a given query.
    This component is used to display search results in the search bar dropdown.
    '''
    query = request.GET.get("q", None)
    starts_with = query.strip().lower()[0]
    context = {}
    
    if query in ["", None]:
        return HttpResponse("")
    
    match starts_with:
        case ">":
            query = query[1:].strip()
            routes = router.get_routes()
            matched_routes = []
            
            for route in routes:
                if query.lower() in route.name.lower():
                    matched_routes.append(route)
            
            context["matched_routes"] = matched_routes[:5]
            
        case _:
            matched_routes = []
    
    return render(
        request,
        "components/global_search.html",
        context
        )
    

