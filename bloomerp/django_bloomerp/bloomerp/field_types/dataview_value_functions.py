from django.db.models import Model
from typing import TYPE_CHECKING

from django.urls import reverse

from bloomerp.utils.labels import safe_object_label

if TYPE_CHECKING:
    from bloomerp.models import ApplicationField


def render_m2m_dataview_value(application_field: "ApplicationField", object: Model) -> str:
    """
    Renders the value of a ManyToManyField for display in a dataview.
    """
    from bloomerp.utils.models import get_detail_base_view_url
    
    # Get the related manager for the ManyToManyField
    related_manager = getattr(object, application_field.field, None)
    if related_manager is None:
        return ""

    # Get the first 3 related objects (or all if there are fewer than 3)
    has_addendum = False
    if related_manager.count() > 3:
        related_objects = related_manager.all()[:3]
        has_addendum = True
        
    
    related_objects = related_manager.all()[:3]

    # Render the related objects as a comma-separated list of their string representations
    div = '<div class="flex flex-wrap gap-1">{content}</div>'
    a_tag = """<a href="{url}" class="badge badge-primary badge-xs hover:underline">{name}</a>"""
    
    for obj in related_objects:
        # Get the URL for the related object (assuming it has a get_absolute_url method)
        url = getattr(obj, "get_absolute_url", lambda: "#")()
        name = safe_object_label(obj)
        a_tag_formatted = a_tag.format(url=url, name=name)
        div = div.replace("{content}", a_tag_formatted + "{content}")
    
    if has_addendum:
        try:
            foreign_url = get_detail_base_view_url(object)
            foreign_url += f"_{application_field.field}_relationship"
            
            addendum_url = reverse(foreign_url, kwargs={"pk": object.pk})
        except:
            addendum_url = "#"
        
        addendum_html = f'<a href="{addendum_url}" class="badge badge-primary badge-xs">+{related_manager.count() - 3} more</a>'
        div = div.replace("{content}", addendum_html + "{content}")
    
    div = div.replace("{content}", "")
    return div


def render_foreign_key_dataview_value(application_field: "ApplicationField", object: Model) -> str:
    """
    Renders the value of a ForeignKey for display in a dataview.
    """
    # Get the related object for the ForeignKey
    related_object = getattr(object, application_field.field, None)
    if related_object is None:
        return ""
    
    # Render the related object as a link to its detail page (assuming it has a get_absolute_url method)
    url = getattr(related_object, "get_absolute_url", lambda: "#")()
    name = safe_object_label(related_object)
    return f'<a href="{url}" class="text-primary hover:underline">{name}</a>'

def render_generic_relation_value(application_field: "ApplicationField", object: Model) -> str:
    """
    Renders the value of a GenericForeignKey for display in a dataview.
    """
    # Get the related object for the GenericForeignKey
    related_manager = getattr(object, application_field.field, None)
    if related_manager is None:
        return ""
    
    
