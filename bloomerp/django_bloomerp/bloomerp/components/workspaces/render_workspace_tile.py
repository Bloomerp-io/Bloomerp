import random
from bloomerp.router import router
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

RANDOM = [
    ('fa-chart-line', 'Revenue', '$10,000'),
    ('fa-users', 'Customers', '500'),
    ('fa-box', 'Products', '150'),
]


@router.route(
    path='components/render_workspace_tile/',
    name='components_render_workspace_tile'
)
def render_workspace_tile(request: HttpRequest) -> HttpResponse:
    icon, title, value = random.choice(RANDOM)
    
    return render(request, 'components/workspaces/render_workspace_tile.html', {'icon': icon, 'title': title, 'value': value})