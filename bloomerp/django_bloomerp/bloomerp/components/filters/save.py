from django.contrib.auth.decorators import login_required
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import render
from bloomerp.router import router

@router.register(
    path="components/filters/save",
    url_name="components_filters_save"
)
@login_required
def save(request: HttpRequest) -> HttpResponse:
    """Saves a specific filter

    Args:
        request (HttpRequest): _description_

    Returns:
        HttpResponse: _description_
    """
