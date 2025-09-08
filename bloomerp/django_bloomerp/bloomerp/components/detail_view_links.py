from bloomerp.utils.router import route
from django.shortcuts import render, redirect
from django.http import HttpResponse, HttpRequest
from bloomerp.forms.core import DetailLinksSelectForm
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.decorators import login_required

@login_required
@route('detail_view_links')
def detail_view_links(request:HttpRequest) -> HttpResponse:
    '''Add component to select detail links for a user'''

    # Get the content type id from the query parameters
    content_type_id = request.POST.get('content_type_id')
    if not content_type_id:
        return HttpResponse('content_type_id required in the query parameters', status=400)
    else:
        ct = ContentType.objects.get(id=content_type_id)
    
    form = DetailLinksSelectForm(
        data =request.POST,
        user = request.user,
        content_type=ct
        )
    
    if form.is_valid():
        form.save()

    # Redirect to the page the url came from
    url = request.META.get('HTTP_REFERER')

    return redirect(url)