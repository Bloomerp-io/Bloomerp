from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bloomerp.models import ApplicationField

from bloomerp.utils.labels import safe_object_label

from django.db.models import Model
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.text import Truncator


MAX_RELATED_OBJECT_LABEL_LENGTH = 60


def render_m2m_dataview_value(application_field: "ApplicationField", object: Model) -> str:
    """
    Renders the value of a ManyToManyField for display in a dataview.
    """
    from bloomerp.utils.models import get_detail_base_view_url

    # Get the related manager for the ManyToManyField
    related_manager = getattr(object, application_field.field, None)
    if related_manager is None:
        return ""

    related_count = related_manager.count()
    related_objects = related_manager.all()[:3]
    badges = []

    for obj in related_objects:
        # Get the URL for the related object (assuming it has a get_absolute_url method)
        url = getattr(obj, "get_absolute_url", lambda: "#")()
        name = Truncator(safe_object_label(obj)).chars(MAX_RELATED_OBJECT_LABEL_LENGTH)
        badges.append(
            format_html(
                '<a href="{}" class="badge badge-primary badge-xs hover:underline">{}</a>',
                url,
                name,
            )
        )

    if related_count > 3:
        try:
            foreign_url = get_detail_base_view_url(object)
            foreign_url += f"_{application_field.field}_relationship"

            addendum_url = reverse(foreign_url, kwargs={"pk": object.pk})
        except:
            addendum_url = "#"

        badges.append(
            format_html(
                '<a href="{}" class="badge badge-primary badge-xs">+{} more</a>',
                addendum_url,
                related_count - 3,
            )
        )

    return format_html(
        '<div class="flex flex-wrap gap-1">{}</div>',
        format_html_join("", "{}", ((badge,) for badge in badges)),
    )


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
    name = Truncator(safe_object_label(related_object)).chars(MAX_RELATED_OBJECT_LABEL_LENGTH)
    return format_html('<a href="{}" class="text-primary hover:underline">{}</a>', url, name)


def render_generic_relation_value(application_field: "ApplicationField", object: Model) -> str:
    """
    Renders the value of a GenericForeignKey for display in a dataview.
    """
    # Get the related object for the GenericForeignKey
    related_manager = getattr(object, application_field.field, None)
    if related_manager is None:
        return ""
