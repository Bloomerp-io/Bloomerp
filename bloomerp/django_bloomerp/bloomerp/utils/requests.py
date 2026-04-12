from typing import Any, Literal
from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.forms import Form
from django.shortcuts import render

def parse_bool_parameter(value : Any, default_value=False) -> bool:
    """
    Function that will parse a string to a boolean value.
    """
    try:
        if isinstance(value, bool):
            return value
        
        if isinstance(value, int):
            return bool(value)
        
        if isinstance(value, str):
            if value.lower() in ['true', '1']:
                return True
            elif value.lower() in ['false', '0']:
                return False
            
        return default_value
    except:
        return default_value    


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


def render_blank_form(
        request : HttpRequest, 
        form:Form, 
        hidden_args:dict, 
        url:str,
        submit_label:str="Submit",
        form_args:dict=None
        ) -> HttpResponse:
    """
    Render a small standalone form fragment used for HTMX panel inserts.

    This helper renders the `utils/blank_form.html` template with the
    provided form and auxiliary values. It is intended for short, self-
    contained form fragments that are loaded into a panel or dropdown via
    HTMX and therefore uses a minimal context.

    Args:
        request: Django `HttpRequest` instance.
        form: A Django `Form` instance to render inside the fragment.
        hidden_args: Mapping of hidden input names to values to include.
        url: The form action URL (also used for HTMX `hx-post`).
        submit_label: Optional label for the submit button.
        form_args: Optional dictionary of additional rendering arguments for
            the template.

    Returns:
        HttpResponse: The rendered blank form fragment.
    """
    return render(
        request=request,
        template_name="utils/blank_form.html",
        context={
            "form":form,
            "hidden_args":hidden_args,
            "url":url,
            "submit_label": submit_label,
            "form_args" : form_args if form_args else {}
        }
    )
    
    
def render_message(request: HttpRequest, message: str, type: Literal["info", "warning", "error", "success"]) -> HttpResponse:
    """Renders a message page

    Args:
        request (HttpRequest): the request object
        message (str): the message to render

    Returns:
        HttpResponse: the response object
    """
    return render(
        request=request,
        template_name="cotton/ui/message.html",
        context={
            "message": message,
            "type": type,
        }
    )

def render_template_and_message(
    request:HttpRequest,
    message:str,
    type: Literal["info", "warning", "error", "success"],
    template_name:str,
    context:dict[str, Any] | None=None,
    hx_swap_oob:Any=None,
    hx_swap_oob_id:str|None=None,
    duration:int=5,
) -> HttpResponse:
    """
    Render a wrapper template that includes another template plus a UI message.

    Args:
        request: The incoming Django request.
        message: The message text shown after the included template.
        type: The message variant passed through to the UI message component.
        template_name: The template that should be included before the message.
        context: Optional context dictionary passed to the wrapper and included template.
        hx_swap_oob: whether you'd like to wrap the content around a hx-swap-oob div with an id. This is the value that'd be given to hx-swap-oob
        hx_swap_oob_id: the id of the div in

    Returns:
        HttpResponse: A rendered response using utils/template_and_message.html.

    Raises:
        ValueError: If context is provided and is not a dictionary.
    """
    if context is None:
        context = {}

    if not isinstance(context, dict):
        raise ValueError("Context should be a dictionary")

    context["template_name"] = template_name
    context["message"] = message
    context["type"] = type

    if hx_swap_oob and not hx_swap_oob_id:
        raise ValueError("ID should be given")
    
    if hx_swap_oob_id and not hx_swap_oob:
        hx_swap_oob = "true"

    if hx_swap_oob and hx_swap_oob_id:
        context["hx_swap_oob"] = hx_swap_oob
        context["hx_swap_oob_id"] = hx_swap_oob_id
        
    context["duration"] = duration
    return render(
        request,
        "utils/template_and_message.html",
        context=context
    )

def render_message(
        request:HttpRequest,
        message:str,
        type:Literal["info", "warning", "error", "success"],
):
    """Renders a message"""
    return render(
        request,
        "cotton/ui/message.html",
        {
            "message" : message,
            "type":type,
        }
    )


def render_page_refresh() -> HttpResponse:
    """Returns a HTMX page refresh"""
    from django_htmx.http import HttpResponseClientRefresh
    return HttpResponseClientRefresh()