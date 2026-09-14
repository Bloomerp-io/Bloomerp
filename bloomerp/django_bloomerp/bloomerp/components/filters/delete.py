from django.contrib.auth.decorators import login_required
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import render
from bloomerp.router import router

@router.register(
    path="components/filters/delete",
    url_name="components_filters_delete"
)
@login_required
def delete(request: HttpRequest) -> HttpResponse:
    """Deletes a specific filter from a specified scope

    Args:
        request (HttpRequest): _description_

    Returns:
        HttpResponse: _description_
    """
