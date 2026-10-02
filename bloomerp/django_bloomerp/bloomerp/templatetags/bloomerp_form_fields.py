"""Render Crispy fields with Bloomerp's shared input styles."""

from typing import ClassVar

from crispy_tailwind.tailwind import CSSContainer
from crispy_tailwind.templatetags.tailwind_field import (
    CrispyTailwindFieldNode,
    tailwind_field,
)
from django import template
from django.forms import BoundField
from django.template.base import Parser, Token

register = template.Library()


class BloomerpInputStyles(CSSContainer):
    """Use shared CSS classes and preserve visible validation errors."""

    def get_input_class(self, field: BoundField) -> str:
        """Return widget styles with an error border that overrides shared CSS."""
        classes = super().get_input_class(field)
        if classes and field.errors:
            classes += " !border-danger-dark focus:!border-danger-dark"
        return classes


class BloomerpFieldNode(CrispyTailwindFieldNode):
    """Reuse Crispy rendering with Bloomerp's CSS as the default style source."""

    default_styles: ClassVar[dict[str, str]] = {
        **CrispyTailwindFieldNode.default_styles,
        **{
            name: "input block w-full"
            for name, styles in CrispyTailwindFieldNode.default_styles.items()
            if styles == CrispyTailwindFieldNode.base_input
        },
        "splitdatetime": "input mr-2",
        "error_border": "border-danger-dark",
    }
    default_container: ClassVar[BloomerpInputStyles] = BloomerpInputStyles(default_styles)


@register.tag(name="bloomerp_field")
def bloomerp_field(parser: Parser, token: Token) -> BloomerpFieldNode:
    """Parse Crispy's field attributes using Bloomerp's default input classes."""
    node = tailwind_field(parser, token)
    return BloomerpFieldNode(node.field, node.attrs)
