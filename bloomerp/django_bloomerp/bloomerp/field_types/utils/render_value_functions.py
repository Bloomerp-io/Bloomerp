from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bloomerp.models import ApplicationField

from bloomerp.utils.labels import safe_object_label
from bloomerp.utils.navigation import supports_main_content_navigation

from django.db.models import Model
from django.forms.utils import flatatt
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.text import Truncator


MAX_RELATED_OBJECT_LABEL_LENGTH = 60


def _related_object_url(obj: Model) -> str:
    """Return an object's detail URL or a harmless anchor when unavailable."""
    get_absolute_url = getattr(obj, "get_absolute_url", None)
    return get_absolute_url() if callable(get_absolute_url) else "#"


def _render_related_link(url: str, label: str, css_class: str) -> str:
    """Render a related link with HTMX only for supported application views."""
    attributes = {"href": url, "class": css_class}
    if supports_main_content_navigation(url):
        attributes.update({
            "hx-get": url,
            "hx-target": "#main-content",
            "hx-swap": "innerHTML",
            "hx-push-url": "true",
        })
    return format_html("<a{}>{}</a>", flatatt(attributes), label)


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
        url = _related_object_url(obj)
        name = Truncator(safe_object_label(obj)).chars(MAX_RELATED_OBJECT_LABEL_LENGTH)
        badges.append(
            _render_related_link(
                url,
                name,
                "badge badge-primary badge-xs hover:underline",
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
            _render_related_link(
                addendum_url,
                f"+{related_count - 3} more",
                "badge badge-primary badge-xs",
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
    url = _related_object_url(related_object)
    name = Truncator(safe_object_label(related_object)).chars(MAX_RELATED_OBJECT_LABEL_LENGTH)
    return _render_related_link(url, name, "text-primary hover:underline")


def render_generic_relation_value(application_field: "ApplicationField", object: Model) -> str:
    """
    Renders the value of a GenericForeignKey for display in a dataview.
    """
    # Get the related object for the GenericForeignKey
    related_manager = getattr(object, application_field.field, None)
    if related_manager is None:
        return ""
