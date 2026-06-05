from django.http import Http404, HttpRequest
from bloomerp.models.definition import ObjectAction, get_model_config
from bloomerp.router import router
from bloomerp.utils.models import get_object_model_and_content_type_or_404

from bloomerp.utils.requests import render_message


@router.register(
    path="components/objects/actions/<int:content_type_id>/<int_or_uuid:object_id>/<str:action_id>/",
    url_name="components_objects_actions"
)
def actions_execute(
    request:HttpRequest, 
    content_type_id:int, 
    object_id:str, 
    action_id:str,
    ):
    """Executes the action

    Args:
        request (HttpRequest): request object
        content_type_id (int): content type id
        object_id (str): the object id
        action_id (str): the action id
    """
    object, ModelCls, _ = get_object_model_and_content_type_or_404(content_type_id, object_id)
    config = get_model_config(ModelCls)
    if not config or not config.object_actions:
        return render_message(request, "Action doesn't exist on model", 'error')
    
    action = None
    for a in config.object_actions:
        if isinstance(a, ObjectAction) and action_id == a.id:
            action = a
            break
    
    if not action:
        raise Http404("Action not found")
    
    try:
        return action.execution_func(request, object)
    except Exception as e:
        return render_message(
            request,
            f"An error occurred: {e}",
            "error"
        )
    
