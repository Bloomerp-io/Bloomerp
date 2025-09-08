from bloomerp.utils.router import route
from django.shortcuts import render
from django.http import HttpResponse, HttpRequest
from bloomerp.forms.core import BloomerpModelForm
from bloomerp.models import Todo, AbstractBloomerpUser
from django.forms import modelform_factory
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.decorators import login_required

@login_required
@route('todos')
def todos(request: HttpRequest) -> HttpResponse:
    """
    Todo component that renders a form to create a new todo item.
    """
    # Get content type and object id from the query string
    content_type_id = request.GET.get('content_type_id')
    object_id = request.GET.get('object_id')

    # Get the filter
    filter_class_dict = {
        'all':'',
        'completed':'',
        'uncompleted':''
    }
    filter = request.GET.get('filter', 'all')

    # Override the filter class
    try:
        filter_class_dict[filter] = 'underline active'
    except KeyError:
        filter_class_dict['all'] = 'underline active'

    # Get the object from the content type and object id
    if content_type_id and object_id:
        content_type = ContentType.objects.get(pk=content_type_id)
        object = content_type.get_object_for_this_type(pk=object_id)
    else:
        object = None


    if request.method == 'POST':
        if request.POST.get('completed_todo_id'):
            todo_id = request.POST.get('completed_todo_id')
            completed_todo = Todo.objects.get(pk=todo_id)
            if completed_todo.is_completed:
                completed_todo.is_completed = False
                completed_todo.datetime_completed = None
            else:
                completed_todo.is_completed = True
                completed_todo.datetime_completed = timezone.now()
            completed_todo.save()

        elif request.POST.get('delete_todo_id'):
            todo_id = request.POST.get('delete_todo_id')
            Todo.objects.get(pk=todo_id).delete()
        else:
            form = initialize_form(request.user, data=request.POST)
            if form.is_valid():
                form.save()
        # Reinitialize form after POST processing
        form = initialize_form(request.user, content_type_id, object_id)
    else:  # GET request
        form = initialize_form(request.user, content_type_id, object_id)

    todos = filter_todos(request.user, content_type_id, object_id)

    # Apply filter on todos
    if filter == 'completed':
        todos = todos.filter(is_completed=True)
    elif filter == 'uncompleted':
        todos = todos.filter(is_completed=False)

    assigned_todos = todos.exclude(assigned_to=request.user)
    my_todos = todos.filter(assigned_to=request.user)

    context = {
        'my_todos': my_todos,
        'assigned_todos': assigned_todos,
        'form': form,
        'content_type_id': content_type_id,
        'object_id': object_id,
        'object': object,
        'filter_class_dict': filter_class_dict
    }
    return render(request, 'components/todos.html', context)



def filter_todos(user: AbstractBloomerpUser, content_type_id: int, object_id: int):
    """
    Filter todos based on the user, content type, and object id.
    """
    my_todos = Todo.objects.filter(assigned_to=user) | Todo.objects.filter(requested_by=user)
    if content_type_id and object_id:
        my_todos = my_todos.filter(content_type=content_type_id, object_id=object_id)
    
    return my_todos.order_by('is_completed', '-priority')


def initialize_form(user, content_type_id=None, object_id=None, data=None):
        """Helper function to create and initialize the form."""
        initial = {'assigned_to': user, 'requested_by' : user}
        if content_type_id and object_id:
            initial.update({'content_type': int(content_type_id), 'object_id': int(object_id)})
        Form = modelform_factory(Todo, form=BloomerpModelForm, exclude=['completed', 'datetime_completed'])
        return Form(model=Todo, user=user, initial=initial, data=data)