from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from registries.route_registry import router

@router.register(
    path='components/project-management/todos/',
    name='components_project_management_todos'
)
def todos(request: HttpRequest) -> HttpResponse:
    
    
    
    
    return render(
        request,
        "components/project_management/todos.html",
    )
    
    