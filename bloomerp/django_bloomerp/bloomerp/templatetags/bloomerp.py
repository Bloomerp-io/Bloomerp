from django import template
from django.db.models.manager import Manager
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from bloomerp.utils.models import get_model_dashboard_view_url, get_list_view_url, get_initials, get_detail_view_url, get_delete_view_url
from django.urls import reverse 
from django.contrib.contenttypes.models import ContentType
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
from bloomerp.services.sectioned_layout_services import (
    build_crud_layout_field_context,
    dump_layout_json as dump_layout_json_service,
    get_object_field_value,
)

register = template.Library()


@register.filter(name="dump_layout_json")
def dump_layout_json_filter(layout):
    """
    Serialize a CRUD layout object or dict for use in `data-layout` attributes.

    Example usage:
    {{ layout|dump_layout_json }}
    """
    return dump_layout_json_service(layout)

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
def delete_view_url(object:Model):
    """
    Returns the delete url of an object.

    Example usage:
    {{ object|delete_view_url }}
    """
    try:
        return reverse(get_delete_view_url(object.__class__), kwargs={'pk': object.pk})
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
        "value_content_type_id": application_field.related_model_id,
    }


@register.inclusion_tag('inclusion_tags/layout_field.html')
def render_detail_view_value(
        object: Model, 
        application_field: ApplicationField, 
        user: AbstractBloomerpUser,
        can_view:bool=False,
        can_edit:bool=False,
        colspan:int=1,
        ):
    """Renders a detail view value

    Args:
        object (Model): the object
        application_field (ApplicationField): the application field
        user (AbstractBloomerpUser): the user

    Returns:
        html: the rendered html
    """
    context = build_crud_layout_field_context(
        application_field=application_field,
        value=get_object_field_value(obj=object, application_field=application_field),
        can_edit=can_edit,
    )
    context["colspan"] = colspan
    return context


@register.inclusion_tag('inclusion_tags/object_preview_value.html')
def render_object_preview_value(
        object: Model,
        application_field: ApplicationField,
        user: AbstractBloomerpUser,
        can_view: bool = False,
        can_edit: bool = False,
        colspan: int = 1,
        ):
    """Renders a detail value inside an object preview without failing the whole preview."""
    context = {
        "application_field": application_field,
        "colspan": colspan,
        "preview_field_error_message": None,
    }

    try:
        detail_context = build_crud_layout_field_context(
            application_field=application_field,
            value=get_object_field_value(obj=object, application_field=application_field),
            can_edit=can_edit,
        )
        detail_context["colspan"] = colspan
        detail_context["preview_field_error_message"] = None
        return detail_context
    except Exception:
        context["preview_field_error_message"] = "Preview is not available for this field."
        return context
    

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
