from django.contrib.auth.decorators import login_required
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import render
from bloomerp.router import router

@router.register(
    path="components/filters/select",
    url_name="components_get"
)
@login_required
def select(request: HttpRequest) -> HttpResponse:
    """Returns 

    Args:
        request (HttpRequest): _description_

    Returns:
        HttpResponse: _description_
    """
