from django import forms


class InputSelectWidget(forms.Widget):
	"""Renders a select when choices are provided, otherwise a text input."""

	def __init__(self, attrs=None):
		self.choices = attrs.pop("choices", []) if attrs else []
		super().__init__(attrs)

	def get_choices(self, attrs=None):
		runtime_attrs = attrs or {}
		if "choices" in runtime_attrs:
			return runtime_attrs.get("choices") or []
		return self.choices or []

	def render(self, name, value, attrs=None, renderer=None):
		widget_attrs = self.build_attrs(self.attrs, attrs)
		choices = widget_attrs.pop("choices", None)

		resolved_choices = choices if choices is not None else self.get_choices(attrs)
		if resolved_choices:
			return forms.Select(
				attrs=widget_attrs,
				choices=resolved_choices,
			).render(name, value, attrs=widget_attrs, renderer=renderer)
        
		return forms.TextInput(
			attrs=widget_attrs,
		).render(name, value, attrs=widget_attrs, renderer=renderer)
