from django import template
from django.db.models.manager import Manager
from django.db.models import Model
from bloomerp.utils.models import get_model_dashboard_view_url, get_list_view_url, get_initials, get_detail_view_url
from django.urls import reverse 
from django.contrib.contenttypes.models import ContentType
from bloomerp.models import Link, Widget
from django.utils.safestring import mark_safe
import uuid
from bloomerp.models import Bookmark, AbstractBloomerpUser, ApplicationField, UserListViewField
from django.db.models.functions import Cast
from django.db.models import DateTimeField, F
from django.db.models import QuerySet
from django.core.signing import dumps, loads
from bloomerp.models import File
import uuid
from django.template.loader import render_to_string
from bloomerp.models import FieldType

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


@register.simple_tag(name='field_value')
def field_value(object:Model, application_field:ApplicationField, user:AbstractBloomerpUser, datatable_item:bool=False):
    '''
    Returns the formatted html value of a field in an object.
    Marks it as safe.

    Example usage:
    {% field_value object application_field user %}
    '''
    DEFAULT_NONE_VALUE = ''
    FILTER_VALUE = ''
    FILTERABLE = False

    try:
        # ------------------------------
        # GETTING THE VALUE OF THE FIELD
        # ------------------------------
        if application_field.field_type != 'OneToManyField':
            value = getattr(object, application_field.field)
            
            if value is None:
                value = DEFAULT_NONE_VALUE

        # ------------------------------
        # FORMATTING BASED ON FIELD TYPE
        # ------------------------------
        if application_field.field_type == 'ForeignKey':
            # Get the value of the field
            try:
                FILTER_VALUE = f'{application_field.field}={value.pk}' 
                FILTERABLE = True

                abosulte_url = value.get_absolute_url()
                value = mark_safe(f'<a href="{abosulte_url}">{value}</a>')
            except AttributeError:
                pass
                        
        elif application_field.field_type == 'DateField':
            # Get the date preferences of the user
            # Can be
            # ("d-m-Y", "Day-Month-Year (15-08-2000)"),
            # ("m-d-Y", "Month-Day-Year (08-15-2000)"),
            # ("Y-m-d", "Year-Month-Day (2000-08-15)"),
            preference = user.date_view_preference

            FILTER_VALUE = f'{application_field.field}={value.strftime("%Y-%m-%d")}'
            FILTERABLE = True

            # Format the date
            if preference == "d-m-Y":
                value = value.strftime("%d-%m-%Y")
            elif preference == "m-d-Y":
                value = value.strftime("%m-%d-%Y")
            elif preference == "Y-m-d":
                value = value.strftime("%Y-%m-%d")
            else:
                value = value.strftime("%d-%m-%Y")

        elif application_field.field_type == 'DateTimeField':
            # Get the datetime preferences of the user
            # Can be 
            # ("d-m-Y H:i", "Day-Month-Year Hour:Minute (15-08-2000 12:30)"),
            # ("m-d-Y H:i", "Month-Day-Year Hour:Minute (08-15-2000 12:30)"),
            # ("Y-m-d H:i", "Year-Month-Day Hour:Minute (2000-08-15 12:30)"),
            preference = user.date_view_preference

            FILTER_VALUE = f'{application_field.field}={value.strftime("%Y-%m-%d %H:%M")}'
            FILTERABLE = True

            # Format the date
            if preference == "d-m-Y H:i":
                value = value.strftime("%d-%m-%Y %H:%M")
            elif preference == "m-d-Y H:i":
                value = value.strftime("%m-%d-%Y %H:%M")
            elif preference == "Y-m-d H:i":
                value = value.strftime("%Y-%m-%d %H:%M")
            else:
                value = value.strftime("%d-%m-%Y %H:%M")

        elif application_field.field_type == 'BloomerpFileField':
            # Get the value of the field
            file:File = getattr(object, application_field.field)
            if file:
                value = mark_safe(f'<a href="{file.file.url}" target="_blank">{file.name}</a>')
            else:
                value = DEFAULT_NONE_VALUE

        elif application_field.field_type == 'ManyToManyField':
            # Get the value of the field
            qs = value.all()

            if not qs:
                value = DEFAULT_NONE_VALUE
            else:
                resp = DEFAULT_NONE_VALUE
                for item in qs[:2]:
                    resp += item.__str__() + ', '
                value = resp + '...'
        
        elif application_field.field_type == 'OneToManyField':
            # Get the value of the field
            try:
                value = getattr(object, f'{application_field.field}_set')
            except:
                value = getattr(object, application_field.field)

            qs = value.all()

            if not qs:
                value = DEFAULT_NONE_VALUE
            else:
                resp = ''
                for item in qs[:2]:
                    resp += item.__str__() + ', '
                value = resp + '...'    
        
        elif application_field.field_type == 'StatusField':
            # Get the value of the field
            filter_value : str = getattr(object, application_field.field)
            FILTER_VALUE = f'{application_field.field}={filter_value}'
            FILTERABLE = True

            # Get color
            color_dict : dict = application_field.meta.get('colors')

            if color_dict:
                color = color_dict.get(filter_value, 'gray')
            else:
                color = 'gray'

            value = mark_safe(f'<span class="badge badge-pill" style="background-color: {color}">{value}</span>')
            
        OTHER_FIELDS = ['AutoField', 'BigAutoField', 'BooleanField', 'CharField', 'TextField', 'IntegerField', 'DecimalField']
        if application_field.field_type in OTHER_FIELDS:
            FILTER_VALUE = f'{application_field.field}={value}'
            FILTERABLE = True

        
        # ------------------------------
        # RETURNING THE VALUE
        # ------------------------------
        if datatable_item:
            if FILTERABLE:
                return mark_safe(f'<td context-menu-filter-value="{FILTER_VALUE}" allow-context-menu={True}>{value}</td>')
            else:
                return mark_safe(f'<td allow-context-menu={True}>{value}</td>')
        else:
            return value

    except Exception as e:
        if datatable_item:
            return mark_safe(f'<td allow-context-menu={False}>{DEFAULT_NONE_VALUE}</td>')
        else:
            return DEFAULT_NONE_VALUE


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


@register.inclusion_tag('snippets/datatable_and_filter.html')
def datatable(
    content_type_id:int,
    user:AbstractBloomerpUser,
    include_actions:bool=True,
    initial_query:str='',
    request=None,
    datatable_id=None,
    bypass_view_permission=False
):
    '''
    Returns a data table for a model.

    Example usage:
    {% datatable content_type_id user include_actions initial_query request datatable_id bypass_view_permission %}
    '''
    # Get the model from the content_type_id
    content_type = ContentType.objects.get(pk=content_type_id)
    model = content_type.model_class()

    # Get the application fields
    application_fields = ApplicationField.objects.filter(content_type=content_type)

    # Create random id for the datatable target
    if not datatable_id:
        datatable_id = 'datatable-' + str(uuid.uuid4())
    else:
        datatable_id = 'datatable-' + str(datatable_id)

    if bypass_view_permission:
        if not initial_query:
            raise ValueError('Initial query must be set if bypass_view_permission is True')

        bypass_view_permission_value = dumps({
            'initial_query' : initial_query,
            'content_type_id': content_type_id,
            'user_id' : user.pk
        })

    # Add the bypass_view_permission_value to the initial_query
    if initial_query and bypass_view_permission:
        initial_query += f'&data_table_bypass_view_permission={bypass_view_permission_value}'
    elif bypass_view_permission and not initial_query:
        initial_query = f'data_table_bypass_view_permission={bypass_view_permission_value}'


    return {
        'model': model,
        'application_fields': application_fields,
        'content_type_id': content_type_id,
        'datatable_id': datatable_id,
        'include_actions': include_actions,
        'initial_query': initial_query,
        'request': request,
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
    except:
        model = object._meta.model
        return reverse(get_detail_view_url(model), kwargs={'pk': object.pk})


@register.inclusion_tag("snippets/calendar.html")
def calendar(queryset: QuerySet, start_date_field: str, end_date_field: str = None, id=None):
    if not id:
        id = str(uuid.uuid4())

    parse = 'Y-m-d'
    queryset = queryset.annotate(date_start=Cast(F(start_date_field), output_field=DateTimeField()))
    if end_date_field:
        queryset = queryset.annotate(date_end=Cast(F(end_date_field), output_field=DateTimeField()))


    return {
        "queryset": queryset,
        "start_date_field": start_date_field,
        "end_date_field": end_date_field,
        "id": id,
        "parse":parse
    }


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
    user: AbstractBloomerpUser
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
        "application_field_id" : application_field.id
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
