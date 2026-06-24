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
    """Render an iterable of objects as a table.

    Args:
        object_list: Iterable or related manager to render.
        fields (str): Comma-separated field or attribute paths.
        empty (str): Message shown when the iterable has no rows.

    Usage:
        {% document_table object_list "field_one,field_two" %}
    """
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


@register.filter
def multiply(value: float, multiplier: float) -> float:
    """Multiplies

    Args:
        value (float): _description_
        multiplier (float): _description_

    Returns:
        float: The result of multiplying the value by the multiplier.

    Usage:
        {{ value|multiply:multiplier }}
    """
    try:
        return value * multiplier
    except TypeError:
        return ""


@register.filter
def divide(value: float, divisor: float) -> float:
    """Divides

    Args:
        value (float): _description_
        divisor (float): _description_

    Returns:
        float: The result of dividing the value by the divisor.

    Usage:
        {{ value|divide:divisor }}
    """
    try:
        return value / divisor
    except (TypeError, ZeroDivisionError):
        return ""


@register.filter
def subtract(value: float, subtrahend: float) -> float:
    """Subtracts

    Args:
        value (float): _description_
        subtrahend (float): _description_

    Returns:
        float: The result of subtracting the subtrahend from the value.

    Usage:
        {{ value|subtract:subtrahend }}
    """
    try:
        return value - subtrahend
    except TypeError:
        return ""


@register.filter
def add(value: float, addend: float) -> float:
    """Adds

    Args:
        value (float): _description_
        addend (float): _description_

    Returns:
        float: The result of adding the addend to the value.

    Usage:
        {{ value|add:addend }}
    """
    try:
        return value + addend
    except TypeError:
        return ""
