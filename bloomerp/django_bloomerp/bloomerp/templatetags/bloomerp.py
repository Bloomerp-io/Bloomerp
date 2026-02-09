from django import template
from django.db.models.manager import Manager
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from bloomerp.utils.models import get_model_dashboard_view_url, get_list_view_url, get_initials, get_detail_view_url
from django.urls import reverse 
from django.contrib.contenttypes.models import ContentType
from bloomerp.models.workspaces import Widget
from django.utils.safestring import mark_safe
from django.utils.html import escape
import re
import uuid
from bloomerp.models import Bookmark, AbstractBloomerpUser, ApplicationField
from django.db.models.functions import Cast
from django.db.models import DateTimeField, F
from django.db.models import QuerySet
from django.core.signing import dumps, loads
from bloomerp.models import File
import uuid
from django.template.loader import render_to_string
from bloomerp.field_types import FieldType
from bloomerp.modules.definition import module_registry

register = template.Library()

@register.filter(name='get_dict_value')
def get_dict_value(dictionary:dict, key:str):
    '''
    Returns the value of a key in a dictionary.

    Example usage:
    {{ dictionary|get_dict_value:key }}
    '''

    return dictionary.get(key)

@register.filter
def model_name(obj:Model):
    '''
    Returns the model name of an object.

    Example usage:
    {{ object|model_name }}
    
    '''
    return obj._meta.model_name

@register.filter
def model_name_plural(obj:Model):
    '''
    Returns the model verbose name of an object.

    Example usage:
    {{ object|model_name_plural }}
    
    '''
    return obj._meta.verbose_name_plural

@register.filter
def model_dashboard_url(content_type:ContentType):
    '''
    Returns the model app dashboard URL of an object.

    Example usage:
    {{ object|model_app_dashboard_url }}
    
    '''
    return reverse(get_model_dashboard_view_url(content_type.model_class()))

@register.filter
def model_name_plural_from_content_type(content_type:ContentType):
    '''
    Returns the model verbose name of an object.

    Example usage:
    {{ object|model_name_plural }}
    
    '''
    return content_type.model_class()._meta.verbose_name_plural


@register.filter
def length(obj) -> int:
    '''
    Returns the length of an object.

    Example usage:
    {{ object|length }}
    
    '''
    return len(obj)


@register.filter
def percentage(value, arg):
    try:
        value = int(value) / int(arg)
        return value*100
    except (ValueError, ZeroDivisionError):
        return 


@register.filter
def getattr_filter(obj, attr):
    '''
    Returns the attribute of an object by name.
    
    Example usage:
    {{ object|getattr:"field_name" }}
    '''
    try:
        return getattr(obj, attr, None)
    except (AttributeError, TypeError):
        return None

   
@register.filter
def get_link_by_id(id:int):
    '''
    Returns the link object with the given id.

    Example usage:
    {{ id|get_link }}

    or 

    {% with id|get_link as link %}
    {% if link %}
    {{ link.name }}
    {% endif %}
    {% endwith %}

    '''
    try:
        return Link.objects.get(pk=id)
    except:
        return 
    
    
@register.filter
def get_widget_by_id(id:int):
    '''
    Returns the widget object with the given id.

    Example usage:
    {{ id|get_widget }}

    or 

    {% with id|get_widget as widget %}
    {% if widget %}
    {{ widget.name }}
    {% endif %}
    {% endwith %}

    '''
    try:
        return Widget.objects.get(pk=id)
    except:
        return 


@register.inclusion_tag('snippets/workspace_item.html')
def workspace_item(item:dict):
    '''
    Returns a workspace item.

    Example usage:
    {% workspace_item item %}
    '''
    # generate random id for each item
    item['id'] = uuid.uuid4()

    return {'item': item}


@register.simple_tag(name='render_link')
def render_link(link_id:int):
    '''
    Returns a link object.

    Example usage:
    {% render_link link_id %}
    '''
    try:
        link = Link.objects.get(pk=link_id)
        if link.is_external_url():
            return mark_safe(f'<a link-id="{link.pk}" class="hover:cursor-pointer text-primary link-item" href="https://{link.url}" target="_blank">{link.name}</a>')
        elif link.is_absolute_url:
            return mark_safe(f'<a link-id="{link.pk}" class="hover:cursor-pointer text-primary link-item" hx-get="{link.url}" hx-target="#main-content" hx-push-url="true">{link.name}</a>')
        elif not link.requires_args():
            return mark_safe(f'<a link-id="{link.pk}" class="hover:cursor-pointer text-primary link-item" hx-get="{reverse(link.url)}" hx-target="#main-content" hx-push-url="true">{link.name}</a>')
        else:
            return mark_safe("<p>Link requires arguments</p>")
    except:
        return mark_safe("<p>Link not found</p>")


@register.inclusion_tag('components/bookmark.html')
def render_bookmark(object:Model, user:AbstractBloomerpUser, size:int, target:str):
    '''
    Returns a bookmark object.

    Example usage:
    {% render_bookmark object user size target %}
    '''
    # Get the content_type_id and object_id from the request
    content_type_id = ContentType.objects.get_for_model(object).pk
    
    # Check if the bookmark allready exists
    bookmarked = Bookmark.objects.filter(user=user, content_type_id=content_type_id, object_id=object.pk).exists()

    return {
        'bookmarked': bookmarked,
        'content_type_id': content_type_id,
        'object_id': object.pk,
        'target' : target,
        'size': size
    }



@register.inclusion_tag('snippets/breadcrumb.html')
def breadcrumb(title:str=None, model:Model = None, object:Model=None):
    '''
    Returns a breadcrumb navigation.

    Example usage:
    {% breadcrumb title model object %}
    '''
    # Init context
    context = {"title": title}

    # Check if the model is set
    if model:
        list_view_url = get_list_view_url(model)
        model_dashboard_view_url = get_model_dashboard_view_url(model)
        model_name_plural = model._meta.verbose_name_plural.title()
        context['list_view_url'] = list_view_url
        context['model_name_plural'] = model_name_plural
        context['model_dashboard_url'] = model_dashboard_view_url
    if object:
        context['object'] = object
    return context


@register.inclusion_tag('snippets/avatar.html')
def avatar(object:Model, avatar_attribute:str='avatar', size:int=30, class_name=''):
    '''
    Returns an avatar object.

    Args:
        object (Model): The object that has the avatar attribute.
        avatar_attribute (str): The attribute name of the avatar. Default is 'avatar'.
        size (int): The size of the avatar. Default is 50.
        class_name (str): The class name of the avatar. Default is ''.

    Example usage:
    {% avatar object avatar_attribute size class_name %}

    '''
    try:
        avatar = getattr(object, avatar_attribute)

        if not hasattr(avatar, 'url'):
            # Get the first letter of the object's string representation
            initials = get_initials(object)
        else:
            initials = None
    except:
        initials = get_initials(object)
        avatar = None

    return {
        'avatar': avatar,
        'size': size,
        'class_name': class_name,
        'initials': initials
    }


@register.simple_tag(takes_context=True)
def generate_uuid(context):
    '''
    Returns a unique id.
    '''
    return str(uuid.uuid4())


@register.simple_tag(takes_context=True)
def load_icon(context:dict, icon:str, size:int=30, cls:str|None=None):
    """Load's an icon"""
    base = "cotton/icons/{}.html"

    try:
        return render_to_string(base.format(icon), context={"size":size, "class":cls})
    except:
        return "Icon not found"


@register.filter
def detail_view_url(object:Model):
    '''
    Returns the absolute url of an object.

    Example usage:
    {{ object|detail_view_url }}

    '''
    try:
        return object.get_absolute_url()
    except Exception:
        try:
            model = object._meta.model
            return reverse(get_detail_view_url(model), kwargs={'pk': object.pk})
        except Exception:
            return ""


@register.filter
def get_nested_attribute(obj, attribute_path: str):
    """Get a nested attribute from an object.

    Args:
        obj (object): The object to get the attribute from.
        attribute_path (str): The path to the attribute.

    Returns:
        object: The value of the attribute.

    Example usage:
    {{ object|get_nested_attribute:'attribute1.attribute2.attribute3' }}
    """
    try:
        for attr in attribute_path.split('.'):
            obj = getattr(obj, attr)
        return obj
    except AttributeError:
        return None
    
    
@register.inclusion_tag('inclusion_tags/dataview_value.html')
def render_dataview_value(
    object: Model,
    application_field: ApplicationField,
    user: AbstractBloomerpUser,
    row_index:int=0,
    column_index:int=0,
    url:str=None,
    split_view_enabled: bool = False,
):
    """Renders a data table value

    Args:
        object (Model): the object
        application_field (ApplicationField): the application field
        user (AbstractBloomerpUser): the user object
        
    Example usage:
    {% render_dataview_value object application_field user %}
    """
    # Get the value of the field
    value = getattr(object, application_field.field, None)
    
    return {
        "value": value,
        "object": object,
        "is_field_type": FieldType.template_context(application_field.field_type),
        "application_field_id" : application_field.id,
        "row_index" : row_index,
        "column_index" : column_index,
        "url" : url,
        "application_field" : application_field,
        "split_view_enabled": split_view_enabled,
    }


@register.inclusion_tag('inclusion_tags/detail_view_value.html')
def render_detail_view_value(
        object: Model, 
        application_field: ApplicationField, 
        user: AbstractBloomerpUser,
        can_view:bool=False,
        can_edit:bool=False
        ):
    """Renders a detail view value

    Args:
        object (Model): the object
        application_field (ApplicationField): the application field
        user (AbstractBloomerpUser): the user

    Returns:
        html: the rendered html
    """
    value = getattr(object, application_field.field, None)
    
    # Get the field type enum
    widget = application_field.get_widget()
    attrs = {
        "class" : "input w-full",
    }
    
    if not can_edit:
        attrs["readonly"] = "readonly"
    
    input = widget.render(
            name=application_field.field,
            value=value,
            attrs=attrs
        )
    
    return {
        "value": value,
        "object": object,
        "application_field": application_field,
        "input": input,
    }
    

@register.simple_tag
def get_icon(name, size=16, **kwargs):
    """
    Renders an icon from the cotton/icons folder.
    
    Example usage:
    {% get_icon name="list" size="16" %}
    """
    try:
        return mark_safe(render_to_string(f"cotton/icons/{name}.html", {'size': size, **kwargs}))
    except template.TemplateDoesNotExist:
        return ""


@register.filter
def make_list_by_comma(value: str):
    """
    Splits a string by comma into a list.
    
    Example usage:
    {{ "Mon,Tue,Wed"|make_list_by_comma }}
    """
    return value.split(',')


@register.filter
def get_item(dictionary, key):
    """
    Gets an item from a dictionary by key. Works with date keys.
    
    Example usage:
    {{ my_dict|get_item:my_key }}
    """
    if dictionary is None:
        return None
    try:
        return dictionary.get(key, [])
    except (AttributeError, TypeError):
        return []


@register.filter
def highlight_query(value, query):
    """Highlight query matches in a string with a yellow background."""
    if value is None:
        return ""

    value_str = str(value)
    query_str = str(query or "").strip()
    if not query_str:
        return value_str

    escaped_value = escape(value_str)
    pattern = re.compile(re.escape(query_str), re.IGNORECASE)

    def _repl(match: re.Match) -> str:
        return f'<span class="bg-yellow-200 text-gray-900 rounded px-1">{match.group(0)}</span>'

    return mark_safe(pattern.sub(_repl, escaped_value))


@register.inclusion_tag('inclusion_tags/sidebar_module_content.html')
def render_sidebar_module_content(request:HttpRequest) -> HttpResponse:
    """Resolves the sidebar content based on the module defined in the url.

    Args:
        request (HttpRequest): The HTTP request object.
        
    Returns:
        HttpResponse: The rendered sidebar content.
    """
    # Get the module from the url
    path_parts = request.path.strip('/').split('/')
    module_id = path_parts[0] if len(path_parts) > 0 else None
    models = module_registry.get_models_for_module(module_id)
    module = module_registry.get(module_id) if module_id else None
    return {
        'module': module,
        'models': models,
    }