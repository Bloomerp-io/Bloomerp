"""Utils for rendering certain items"""
from django.http import HttpRequest
from django.http import HttpResponse
from django.forms import Form
from django.shortcuts import render
from django.db.models import Model
from django.contrib.contenttypes.models import ContentType

def render_blank_form(request : HttpRequest, form:Form, hidden_args:dict, url:str) -> HttpResponse:
    """Renders a blank form
    """
    return render(
        request=request,
        template_name="utils/blank_form.html",
        context={
            "form":form,
            "hidden_args":hidden_args,
            "url":url,
        }
    )
    
    
def get_object_from_request(
    request:HttpRequest,
    content_type_id_arg:str="content_type_id",
    object_id_arg:str="object_id"
    ) -> tuple[Model, str, str]:
    """Returns an object based on the request
    
    Args:
        request : the request object
        content_type_id_arg : the name of the content type argument
        object_id : the name of the content type argument
    
    Returns:
        the object
    """
    content_type_id = None
    object_id = None
    
    match request.method:
        case "GET":
            content_type_id = request.GET.get(content_type_id_arg)
            object_id = request.GET.get(object_id_arg)
        case "POST":
            content_type_id = request.POST.get(content_type_id_arg)
            object_id = request.POST.get(object_id_arg)
        case _:
            pass
        
    ERROR_RESP = None, object_id, content_type_id
        
    if not object_id or not content_type_id:
        return ERROR_RESP
    
    try:
        ct = ContentType.objects.get(id=content_type_id)
    except ContentType.DoesNotExist:
        return ERROR_RESP
    
    try:
        return ct.get_object_for_this_type(id=object_id), object_id, content_type_id
    except:
        return ERROR_RESP
                
    
    