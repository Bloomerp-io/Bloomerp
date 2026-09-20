from typing import Any

from django import forms
from django.utils.html import format_html, format_html_join
from django.views.generic.edit import FormMixin

from bloomerp.models import LayoutItem
from bloomerp.services.sectioned_layout_services import get_layout_widget_attrs
from bloomerp.views.mixins.layout_mixin import LayoutMixin


class LayoutFormMixin(LayoutMixin, FormMixin):
    """Transform form fields into rendered layout items."""

    apply_permissions: bool = True
    label_extractor_func = lambda self, item: self.render_label(item)
    content_extractor_func = lambda self, item: self.render_field(item)
    extra_attrs_extractor_func = lambda self, item: self.render_extra_attrs(item)

    can_change = False
    
    def render_extra_attrs(self, item: LayoutItem) -> dict:
        return {
            "data-required": str(self.resolve_is_required(item)),
        }
    
    def render_label(self, item: LayoutItem):
        label = self.resolve_form_label(item)
        is_required = self.resolve_is_required(item)
        
        if is_required:
            label = format_html("{} <span class='text-red-500'>*</span>", label)
        
        return label

    def resolve_is_required(self, item: LayoutItem) -> bool:
        form_field = self.get_form().fields.get(self.resolve_form_key(item))
        return bool(form_field and form_field.required)

    def get_layout_widget(
        self,
        item: LayoutItem,
        form_field: forms.Field,
    ) -> forms.Widget:
        """Return the widget used for one layout item."""
        return form_field.widget

    def apply_layout_widget_config(self, form):
        """Apply item-specific widget configuration before validation or rendering."""
        for row in self.get_layout().rows:
            for item in row.items:
                field_name = self.resolve_form_key(item)
                form_field = form.fields.get(field_name)
                if form_field is None:
                    continue
                form_field.widget = self.get_layout_widget(item, form_field)
        return form

    def render_field(self, item: LayoutItem) -> str:
        """Render a bound field and expose its help text on the layout item."""
        bound_field = self.get_form()[self.resolve_form_key(item)]
        item.help_text = str(bound_field.help_text) if bound_field.help_text else None
        
        attrs = get_layout_widget_attrs(widget=bound_field.field.widget)
        if bound_field.field.disabled:
            attrs["disabled"] = "disabled"
        if bound_field.errors:
            attrs["class"] += " border-red-500"

        errors = format_html_join(
            "",
            '<div class="mt-1 text-sm text-red-600">{}</div>',
            ((error,) for error in bound_field.errors),
        )
        return format_html("{}{}", bound_field.as_widget(attrs=attrs), errors)

    def resolve_form_key(self, item: LayoutItem) -> str:
        return item.id

    def resolve_form_label(self, item: LayoutItem) -> str:
        return self.get_form()[self.resolve_form_key(item)].label

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        form = self.get_form()
        layout_field_names = {
            self.resolve_form_key(item)
            for row in self.get_layout().rows
            for item in row.items
        }
        hidden_field_errors = [
            f"{form.fields[field_name].label}: {error}"
            for field_name, errors in form.errors.items()
            if field_name != "__all__" and field_name not in layout_field_names
            for error in errors
        ]
        context["layout_has_form"] = True
        context["layout_non_field_errors"] = [
            *form.non_field_errors(),
            *hidden_field_errors,
        ]
        return context
