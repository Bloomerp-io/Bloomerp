from django.contrib.auth.decorators import login_required
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import render
from bloomerp.router import router

@router.register(
    path="components/filters/get",
    url_name="components_get"
)
@login_required
def get(request: HttpRequest) -> HttpResponse:
    """Returns a set saved set of filters for a particular scope

    Args:
        request (HttpRequest): _description_

    Returns:
        HttpResponse: _description_
    """
    
