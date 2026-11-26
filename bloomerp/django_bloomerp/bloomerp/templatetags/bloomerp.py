import json
import re
import uuid
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import bleach
from django import template
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import (
    FieldDoesNotExist,
    ImproperlyConfigured,
    ObjectDoesNotExist,
)
from django.db.models import ForeignKey, Model
from django.forms.utils import flatatt
from django.http import HttpRequest
from django.urls import NoReverseMatch, reverse
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe
from django.utils.text import Truncator
from django.utils.translation import gettext as _

from bloomerp.config.settings import BLOOMERP_LANGUAGES
from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.models import AbstractBloomerpUser, ApplicationField
from bloomerp.models.definition import (
    DataviewActionContext,
    ObjectActionContext,
    ObjectActionDefinition,
)
from bloomerp.models.users.base_preference import BasePreference
from bloomerp.models.workspaces.sidebar import Sidebar
from bloomerp.permissions.manager import (
    FIELD_ACCESS_CONTROLLED_ANNOTATION,
    field_access_annotation_name,
)
from bloomerp.services.action_services import render_action, with_dataview_context
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.services.sectioned_layout_services import (
    dump_layout_json as dump_layout_json_service,
)
from bloomerp.utils.models import get_detail_view_url, get_initials
from bloomerp.utils.rich_text import sanitize_html
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget
from bloomerp.widgets.icon_picker_widget import (
    parse_icon_value as parse_icon_value_service,
)

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


@register.filter
def avatar_size(size: int | float | str) -> str:
    """Convert numeric avatar sizes to pixels while preserving explicit CSS units."""
    value = str(size)
    try:
        float(value)
    except ValueError:
        return value
    return f"{value}px"


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

    
def _foreign_preview_target(obj: Model, application_field: ApplicationField) -> Model | None:
    """Resolve only an existing concrete foreign-key target, never collections or labels."""
    try:
        if not isinstance(application_field._get_model_field(), ForeignKey):
            return None
        related = getattr(obj, application_field.field, None)
    except (FieldDoesNotExist, ObjectDoesNotExist):
        return None
    return related if isinstance(related, Model) and related.pk is not None else None


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
            value = application_field.get_field_type().resolved_render_value(application_field, object)
        except Exception:
            value = None
    else:
        value = ""
    
    data_value = value
    if can_view and application_field.advanced_rendering:
        # Cell filtering/copying must use the underlying value, not custom HTML.
        try:
            data_value = getattr(object, application_field.field, None)
        except Exception:  # noqa: BLE001 - match the guarded cell renderer above.
            data_value = None
    foreign_preview = None
    if can_view and value is not None and (not isinstance(value, str) or value != ""):
        foreign_preview = _foreign_preview_target(object, application_field)
        if foreign_preview is not None:
            # Preserve trusted rendered links; escape plain relation labels.
            value = format_html("{}", value)
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
        "foreign_preview_object_id": foreign_preview.pk if foreign_preview is not None else None,
        "foreign_preview_content_type_id": (
            ContentType.objects.get_for_model(foreign_preview).pk
            if foreign_preview is not None else None
        ),
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
        ) -> dict[str, Any]:
    """Render an authorized preview value without inputs or cross-field failures."""
    context = {
        "application_field": application_field,
        "colspan": colspan,
        "preview_field_error_message": None,
    }

    if not can_view:
        return {"can_view": False}

    context["can_view"] = True
    try:
        field_type = application_field.get_field_type()
        value, used_advanced_template = field_type.resolved_render_value_with_source(
            application_field, object,
        )
        # Only legacy HTML strings need the rich-text sanitizer. Successfully
        # rendered trusted templates retain their markup and escaped values.
        if (
            not used_advanced_template
            and value is not None
            and field_type.id in {"TextField", "EmailField", "URLField", "FileField"}
        ):
            value = mark_safe(sanitize_html(str(value)))
        context["value"] = value
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
def dataview_item_url(obj: Model, dataview: DataviewActionContext | None) -> str:
    """Address a row by its originating view even if it displays another model."""
    if not dataview:
        return ""
    try:
        path = reverse(
            "components_dataview_item",
            kwargs={"content_type_id": dataview.content_type.pk, "object_id": obj.pk},
        )
    except NoReverseMatch:
        return ""  # Some custom models use keys outside the item route's integer/UUID converter.
    return with_dataview_context(path, dataview)


@register.simple_tag
def dataview_record_attrs(
    obj: Model, dataview: DataviewActionContext | None, row_index: int,
) -> str:
    """Render the shared attributes used to identify and reload an item in its DataView."""
    return flatatt({
        "data-dataview-record": True,
        "data-object-id": obj.pk,
        "data-dataview-record-content-type-id": ContentType.objects.get_for_model(obj).pk,
        "data-dataview-item-index": row_index,
        "data-dataview-item-url": dataview_item_url(obj, dataview),
    })


@register.simple_tag
def render_object_action(
    action: ObjectActionDefinition,
    object: Model,
    request: HttpRequest,
    content_type_id: int | None = None,
    dataview: DataviewActionContext | None = None,
) -> str:
    """Render a configured action on a detail page or for a dataview record."""
    dataview = dataview or None
    content_type = (
        ContentType.objects.get_for_id(content_type_id) if content_type_id
        else ContentType.objects.get_for_model(object)
    )
    context = ObjectActionContext(
        request=request,
        model=object._meta.model,
        content_type=content_type,
        object=object,
        surface="dataview_item" if dataview is not None else "detail",
        dataview=dataview,
    )

    def execution_url(action_id: str) -> str:
        """Address the record and configured action callback."""
        return reverse(
            "components_objects_actions",
            kwargs={
                "content_type_id": content_type.pk,
                "object_id": object.pk,
                "action_id": action_id,
            },
        )

    return mark_safe(render_action(action, context, {
        "object": object,
        "request": request,
        "content_type_id": content_type.pk,
    }, execution_url))


@register.simple_tag
def selected_sidebar(user: AbstractBloomerpUser) -> BasePreference | None:
    """Load the user's selected sidebar for pages rendered outside the view mixins."""
    return PreferenceManager(user).get_or_create_selected(Sidebar)


@register.simple_tag
def view_as_user_widget(user: AbstractBloomerpUser) -> str:
    """Render the account switcher with active users other than the signed-in user."""
    user_model = get_user_model()
    choices = Filter(
        connector="AND",
        conditions=[
            FilterCondition(field_path="is_active", lookup_id="equals", value=True),
            FilterCondition(
                field_path=user_model.USERNAME_FIELD,
                lookup_id="not_equals",
                value=user.get_username(),
            ),
        ],
    )
    search_label = _("Search users")
    return ForeignFieldWidget(
        model=user_model,
        attrs={
            "aria_label": search_label,
            "placeholder": search_label,
            "selection_only": True,
            "choices_filter": f"[{choices.model_dump_json()}]",
        },
    ).render("view_as_user", None)


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
