from django import forms
from fa6_icons import icons


DEFAULT_ICON_CHOICES = [
    {"value": "fa-solid fa-folder", "label": "Folder"},
    {"value": "fa-solid fa-dollar-sign", "label": "Dollar"},
    {"value": "fa-solid fa-book", "label": "Book"},
    {"value": "fa-solid fa-graduation-cap", "label": "Graduation"},
    {"value": "fa-solid fa-pen", "label": "Pen"},
    {"value": "fa-solid fa-tag", "label": "Tag"},
    {"value": "fa-solid fa-code", "label": "Code"},
    {"value": "fa-solid fa-terminal", "label": "Terminal"},
    {"value": "fa-solid fa-music", "label": "Music"},
    {"value": "fa-solid fa-cake-candles", "label": "Cake"},
    {"value": "fa-solid fa-scissors", "label": "Scissors"},
    {"value": "fa-solid fa-palette", "label": "Palette"},
    {"value": "fa-solid fa-stethoscope", "label": "Stethoscope"},
    {"value": "fa-solid fa-gear", "label": "Settings"},
    {"value": "fa-solid fa-leaf", "label": "Leaf"},
    {"value": "fa-solid fa-briefcase", "label": "Briefcase"},
    {"value": "fa-solid fa-chart-bar", "label": "Chart"},
    {"value": "fa-solid fa-user", "label": "User"},
    {"value": "fa-solid fa-dumbbell", "label": "Fitness"},
    {"value": "fa-solid fa-book-open", "label": "Open Book"},
    {"value": "fa-solid fa-scale-balanced", "label": "Scale"},
    {"value": "fa-solid fa-globe", "label": "Globe"},
    {"value": "fa-solid fa-paw", "label": "Paw"},
    {"value": "fa-solid fa-flask", "label": "Flask"},
    {"value": "fa-solid fa-brain", "label": "Brain"},
    {"value": "fa-solid fa-heart", "label": "Heart"},
    {"value": "fa-solid fa-gift", "label": "Gift"},
    {"value": "fa-solid fa-bolt", "label": "Bolt"},
    {"value": "fa-solid fa-star", "label": "Star"},
    {"value": "fa-solid fa-camera", "label": "Camera"},
    {"value": "fa-solid fa-comment", "label": "Comment"},
    {"value": "fa-solid fa-cloud", "label": "Cloud"},
    {"value": "fa-solid fa-calendar", "label": "Calendar"},
    {"value": "fa-solid fa-check", "label": "Check"},
    {"value": "fa-solid fa-fire", "label": "Fire"},
]


def normalize_icon_choices(icons):
    if icons is None:
        return list(DEFAULT_ICON_CHOICES)

    normalized = []
    for icon in icons:
        if isinstance(icon, dict):
            value = str(icon.get("value", "")).strip()
            label = str(icon.get("label", value)).strip()
        elif isinstance(icon, (list, tuple)) and len(icon) >= 1:
            value = str(icon[0]).strip()
            label = str(icon[1]).strip() if len(icon) > 1 else value
        else:
            value = str(icon).strip()
            label = value

        if not value:
            continue

        normalized.append({"value": value, "label": label})

    return normalized


def get_icon_values(icons):
    return [icon["value"] for icon in normalize_icon_choices(icons)]


class IconPickerWidget(forms.Widget):
    template_name = "widgets/icon_picker_widget.html"

    def __init__(self, attrs=None, icons=None):
        attrs = attrs or {}
        existing_class = attrs.get("class", "").strip()
        if "input" not in existing_class:
            attrs["class"] = f"input w-full {existing_class}".strip()
        super().__init__(attrs)
        self.icons = normalize_icon_choices(icons)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        icon_lookup = {icon["value"]: icon["label"] for icon in self.icons}
        selected_value = context["widget"].get("value") or ""
        selected_label = icon_lookup.get(selected_value, "")

        invalid = False
        if (attrs or {}).get("aria-invalid", "false") == "true":
            invalid = True

        context["widget"].update(
            {
                "icons": self.icons,
                "selected_label": selected_label,
                "invalid": invalid,
            }
        )
        return context
