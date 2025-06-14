from bloomerp.utils.router import route
from django.shortcuts import render
from django.http import HttpResponse, HttpRequest
from django.contrib.auth.decorators import login_required

@login_required
@route('delete_object')
def delete_object(request:HttpRequest) -> HttpResponse:
    """Component to delete an object"""
    
    
    context = {}
    return render(request, 'components/objects/delete_object.html', context)