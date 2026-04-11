from django import forms

from bloomerp.forms.layouts import BloomerpModelformHelper
from bloomerp.models.workspaces.tile import Tile
from bloomerp.widgets.icon_picker_widget import DEFAULT_ICON_CHOICES, get_icon_values


MODEL_DEFAULT_TILE_ICON = Tile._meta.get_field("icon").default
VALID_TILE_ICONS = get_icon_values(DEFAULT_ICON_CHOICES)
DEFAULT_TILE_ICON = (
    MODEL_DEFAULT_TILE_ICON
    if MODEL_DEFAULT_TILE_ICON in VALID_TILE_ICONS
    else "fa-solid fa-chart-bar"
)


class TileMetadataForm(forms.ModelForm):
    class Meta:
        model = Tile
        fields = ["name", "description", "icon"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.helper = BloomerpModelformHelper([])

        self.fields["name"].required = False
        self.fields["name"].label = ""
        self.fields["name"].help_text = ""
        self.fields["name"].widget.attrs.update({
            "class": "input h-11",
            "placeholder": "Name",
        })
        self.fields["description"].required = False
        self.fields["description"].label = ""
        self.fields["description"].help_text = ""
        self.fields["description"].widget.attrs.update({
            "class": "input h-11 min-h-11 resize-none",
            "rows": 1,
            "placeholder": "Description",
        })
        self.fields["icon"].required = False
        self.fields["icon"].label = ""
        self.fields["icon"].help_text = ""
        self.fields["icon"].widget.attrs.update({
            "class": "input h-11 w-full",
        })

        if not self.is_bound and not self.initial.get("icon"):
            self.initial["icon"] = DEFAULT_TILE_ICON

    def clean_icon(self) -> str:
        return self.cleaned_data.get("icon") or DEFAULT_TILE_ICON