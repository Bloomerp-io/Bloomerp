from django import forms
from bloomerp.models.workspaces.sidebar_item import (
    DEFAULT_FOLDER_ICON,
    DEFAULT_LINK_ICON,
    SidebarItem,
)


class BaseSidebarItemForm(forms.ModelForm):
    default_icon = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({"class": "input"})

        self.fields["icon"].required = False
        self.fields["icon"].initial = self.default_icon

        if not self.is_bound and not self.initial.get("icon"):
            self.initial["icon"] = self.default_icon

    def clean_icon(self) -> str:
        return self.cleaned_data.get("icon") or self.default_icon


class CreateSidebarFolderForm(BaseSidebarItemForm):
    default_icon = DEFAULT_FOLDER_ICON

    class Meta:
        model = SidebarItem
        fields = ["name", "icon"]

    def is_valid(self):
        # Set the is_folder attribute to true before validation so that any folder-specific validation logic is applied
        self.instance.is_folder = True

        return super().is_valid()


class CreateLinkSidebarItemForm(BaseSidebarItemForm):
    default_icon = DEFAULT_LINK_ICON

    class Meta:
        model = SidebarItem
        fields = ["name", "icon", "url"]

    def is_valid(self):
        # Set the is_folder attribute to false before validation so that any link-specific validation logic is applied
        self.instance.is_folder = False

        return super().is_valid()
