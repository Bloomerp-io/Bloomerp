from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from bloomerp.models.project_management.todo import TodoEffort, TodoPriority, TodoStatus
from bloomerp.router import router

@router.register(
    path='components/project-management/create-todo/',
    name='components_project_management_create_todo'
)
def create_todo(request: HttpRequest) -> HttpResponse:
    """Component that returns a create todo form.

    Args:
        request (HttpRequest): the request object

    Returns:
        HttpResponse: form to create a todo
    """
    if request.method == "GET":
        
        return render(
            request,
            "components/project_management/create_todo.html",
            {
                "status_choices" : TodoStatus.choices,
                "priority_choices" : TodoPriority.choices,
                "effort_choices" : TodoEffort.choices,
            }
        )
    elif request.method == "POST":
        # Handle form submission
        pass
    else:
        return HttpResponse(status=405)  # Method Not Allowed
    
    
    
    