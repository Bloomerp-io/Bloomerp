from collections.abc import Iterable

from django import template
from django.db.models.manager import BaseManager
from django.utils.html import conditional_escape, format_html, format_html_join

register = template.Library()


def _resolve_value(obj, attribute_path: str):
    value = obj
    for attribute in attribute_path.split("."):
        if value is None:
            return ""
        if isinstance(value, dict):
            value = value.get(attribute, "")
        else:
            value = getattr(value, attribute, "")
        if callable(value):
            value = value()
    return value


def _coerce_iterable(value):
    if isinstance(value, BaseManager):
        return value.all()
    if hasattr(value, "all") and callable(value.all):
        return value.all()
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, dict)):
        return value
    return []


@register.simple_tag
def document_table(object_list, fields: str, empty: str = "No records"):
    field_names = [field.strip() for field in fields.split(",") if field.strip()]
    if not field_names:
        return ""

    rows = list(_coerce_iterable(object_list))
    headers = [field.replace("_", " ").replace(".", " ").title() for field in field_names]

    header_html = format_html_join(
        "",
        "<th>{}</th>",
        ((header,) for header in headers),
    )

    if not rows:
        return format_html(
            "<table class=\"document-template-table\"><thead><tr>{}</tr></thead>"
            "<tbody><tr><td colspan=\"{}\">{}</td></tr></tbody></table>",
            header_html,
            len(field_names),
            empty,
        )

    body_html = format_html_join(
        "",
        "<tr>{}</tr>",
        (
            (
                format_html_join(
                    "",
                    "<td>{}</td>",
                    ((conditional_escape(_resolve_value(row, field)),) for field in field_names),
                ),
            )
            for row in rows
        ),
    )

    return format_html(
        "<table class=\"document-template-table\"><thead><tr>{}</tr></thead><tbody>{}</tbody></table>",
        header_html,
        body_html,
    )
