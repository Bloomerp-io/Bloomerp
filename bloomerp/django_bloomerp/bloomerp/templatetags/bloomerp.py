import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import bleach
from django import template
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Model
from django.http import HttpRequest
from bloomerp.models.definition import ObjectAction, ObjectHTMLAction, ObjectModalAction
from bloomerp.models.users.base_preference import BasePreference
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.utils.models import get_initials, get_detail_view_url, get_delete_view_url
from django.urls import reverse 
from django.contrib.contenttypes.models import ContentType
from django.utils.safestring import mark_safe
from django.utils.html import escape, format_html
from django.utils.text import Truncator
from django.utils.translation import gettext
from django.middleware.csrf import get_token
import re
import uuid
from bloomerp.models import Bookmark, AbstractBloomerpUser, ApplicationField
import uuid
from django.template.loader import render_to_string
from django.forms.utils import flatatt
from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
from bloomerp.config.settings import BLOOMERP_LANGUAGES
from bloomerp.permissions.manager import (
    FIELD_ACCESS_CONTROLLED_ANNOTATION,
    field_access_annotation_name,
)
from bloomerp.services.sectioned_layout_services import (
    build_crud_layout_field_context,
    dump_layout_json as dump_layout_json_service,
    get_object_field_value,
)
from bloomerp.widgets.icon_picker_widget import parse_icon_value as parse_icon_value_service

register = template.Library()

ACTIVITY_LOG_VALUE_MAX_LENGTH = 300
ACTIVITY_LOG_ALLOWED_TAGS = {
    "a",
    "blockquote",
    "br",
    "code",
    "em",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "ul",
}
ACTIVITY_LOG_ALLOWED_ATTRIBUTES = {
    "a": ["href", "title"],
}
ACTIVITY_LOG_ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


@register.simple_tag
def bloomerp_asset_version() -> str:
    """Invalidate rebuilt development CSS using the current build manifest timestamp."""
    if settings.DEBUG:
        from django.contrib.staticfiles import finders

        entry = finders.find("bloomerp/js/dist/manifest.json")
        if entry:
            try:
                return f"dev-{Path(entry).stat().st_mtime_ns}"
            except FileNotFoundError:
                pass  # The build may replace the entry between lookup and stat.
    try:
        return version("Bloomerp")
    except PackageNotFoundError:
        return "dev"


@register.simple_tag
def bloomerp_vite_entry() -> str:
    """Resolve the hashed production entry shared by the page and lazy imports."""
    from django.contrib.staticfiles import finders

    manifest_path = finders.find("bloomerp/js/dist/manifest.json")
    message = "Bloomerp's Vite manifest is missing or invalid. Run npm run build:js in bloomerp/static_src."
    if not manifest_path:
        raise ImproperlyConfigured(message)

    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        entry = manifest["ts/entry.ts"]
        filename = entry["file"]
        if not entry.get("isEntry") or not isinstance(filename, str) or not filename:
            raise ValueError("Missing Vite entry filename")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise ImproperlyConfigured(message) from error

    return f"bloomerp/js/dist/{filename}"


@register.simple_tag
def get_bloomerp_languages() -> list[tuple[str, str]]:
    """Return the languages exposed by BloomERP's language selector."""
    return getattr(settings, "BLOOMERP_LANGUAGES", BLOOMERP_LANGUAGES)


@register.filter
def activity_log_html(value):
    """Return length-limited editor HTML that is safe to render in an activity log."""
    if value is None:
        return ""

    cleaned_html = bleach.clean(
        str(value),
        tags=ACTIVITY_LOG_ALLOWED_TAGS,
        attributes=ACTIVITY_LOG_ALLOWED_ATTRIBUTES,
        protocols=ACTIVITY_LOG_ALLOWED_PROTOCOLS,
        strip=True,
    )
    truncated_html = Truncator(cleaned_html).chars(
        ACTIVITY_LOG_VALUE_MAX_LENGTH,
        html=True,
    )
    return mark_safe(truncated_html)


@register.filter(name="dump_layout_json")
def dump_layout_json_filter(layout):
    """
    Serialize a CRUD layout object or dict for use in `data-layout` attributes.

    Example usage:
    {{ layout|dump_layout_json }}
    """
    return dump_layout_json_service(layout)

@register.filter(name="dump_json")
def dump_json_filter(data):
    """
    Serialize a Python object to JSON for use in `data-*` attributes.

    Example usage:
    {{ data|dump_json }}
    """
    return json.dumps(data)

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

    
@register.inclusion_tag('inclusion_tags/dataview_value.html')
def render_dataview_value(
    object: Model,
    application_field: ApplicationField,
    user: AbstractBloomerpUser,
    row_index:int=0,
    column_index:int=0,
    url: str | None = None,
    split_view_enabled: bool = False,
) -> dict[str, Any]:
    """Renders a data table value

    Args:
        object (Model): the object
        application_field (ApplicationField): the application field
        user (AbstractBloomerpUser): the user object
        
    Example usage:
    {% render_dataview_value object application_field user %}
    """
    can_view = getattr(
        object,
        field_access_annotation_name(application_field),
        True,
    )
    if can_view:
        try:
            value = application_field.get_field_type().render_value(application_field, object)
        except Exception:
            value = None
    else:
        value = ""
    
    data_value = value
    if can_view and application_field.get_field_type().id in {"CharField", "ChoiceField"}:
        # Display labels can be localized; filters still need the stored choice key.
        data_value = getattr(object, application_field.field, None)

    return {
        "value": value,
        "data_value": data_value,
        "object": object,
        "is_field_type": FIELD_TYPE_REGISTRY.template_context(application_field.get_field_type()),
        "application_field_id" : application_field.id,
        "row_index" : row_index,
        "column_index" : column_index,
        "url" : url,
        "application_field" : application_field,
        "split_view_enabled": split_view_enabled,
        "value_content_type_id": application_field.related_model_id,
        "object_string": (
            ""
            if getattr(object, FIELD_ACCESS_CONTROLLED_ANNOTATION, False)
            else str(object)
        ),
    }


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


@register.filter
def parse_icon_value(value):
    """Split a stored icon value into glyph and color-chip classes for templates."""
    return parse_icon_value_service(value)



@register.simple_tag
def render_object_action(
    action:ObjectAction|ObjectHTMLAction|ObjectModalAction,
    object:Model,
    request:HttpRequest,
    content_type_id:int|None=None,
) -> str:
    """Render an authorized action with its response target and escaped button attributes."""
    try:
        should_render_action = action.should_render_func(request, object)
    except:
        should_render_action = False
    
    if not should_render_action:
        return ""

    if isinstance(action, ObjectHTMLAction):
        return mark_safe(
            render_to_string(
                action.template_name,
                {
                    "action": action,
                    "object": object,
                    "request": request,
                    "content_type_id": content_type_id,
                },
                request=request,
            )
        )
    
    if isinstance(action, ObjectModalAction):
        return format_html(
            (
                '<button class="btn btn-xs btn-{style}" '
                'hx-get="{url}" '
                'hx-target="#bloomerp-general-use-modal-body" '
                'bloomerp-set-modal-title-for="bloomerp-general-use-modal" '
                'bloomerp-set-modal-title-to="{title}" '
                'bloomerp-set-modal-size-to="{size}" '
                'bloomerp-open-modal="bloomerp-general-use-modal">'
                '{label}'
                '</button>'
            ),
            style=action.style,
            url=action.endpoint(object),
            label=gettext(action.label),
            title=gettext(action.modal_title) if action.modal_title else "",
            size=action.modal_size,
        )

    if content_type_id is None:
        content_type_id = ContentType.objects.get_for_model(object).pk

    attrs = {
        "class": f"btn btn-xs btn-{action.style}",
        "hx-post": reverse(
            "components_objects_actions",
            kwargs={
                "content_type_id": content_type_id,
                "object_id": object.pk,
                "action_id": action.id,
            },
        ),
        "hx-vals": json.dumps({"csrfmiddlewaretoken": get_token(request)}),
        **(action.button_attrs or {}),
        "hx-target": action.target,
    }
    return format_html("<button{}>{}</button>", flatatt(attrs), gettext(action.label))
    
@register.simple_tag
def can_manage_preference_object(user:AbstractBloomerpUser, object:BasePreference) -> bool:
    """Checks if a user can manage a preference object.

    Args:
        user (AbstractBloomerpUser): the user
        object (BasePreference): the object
    Returns:
        bool: whether the user can manage the object or not.
        
    Example usage:
    {% can_manage_preference_object user object as can_manage %}
    """
    try:
        manager = PreferenceManager(user)
        return manager.can_manage(object)
    except:
        return False
