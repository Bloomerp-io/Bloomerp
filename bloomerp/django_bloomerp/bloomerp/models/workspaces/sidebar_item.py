from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models
from django.db import transaction
from bloomerp.model_fields.icon_field import IconField
from typing import Self

from bloomerp.models.workspaces.sidebar import Sidebar

DEFAULT_FOLDER_ICON = "fa-solid fa-folder"
DEFAULT_LINK_ICON = "fa-solid fa-link"
EXTERNAL_URL_VALIDATOR = URLValidator(schemes=["http", "https"])


def is_internal_sidebar_url(url: str | None) -> bool:
    """Treat root-relative application paths as internal HTMX navigations."""
    if not url:
        return False

    parsed = urlsplit(url)
    return not parsed.scheme and not parsed.netloc and url.startswith("/")


class SidebarItemManager(models.Manager):
    # Things 
    pass

class SidebarItem(models.Model):
    """
    A sidebar item is something that appears in the sidebar. It can be a link to a particular page, or it can be a folder that contains other sidebar items. Each user can have multiple sidebar items, and they can be organized in a hierarchical structure using the parent field.
    """
    class Meta:
        db_table = "bloomerp_sidebar_item"

    sidebar = models.ForeignKey(
        to="Sidebar",
        on_delete=models.CASCADE,
        related_name="items"
    )
    name = models.CharField(
        max_length=255,
        help_text="Name of the sidebar item.",
    )
    icon = IconField(
        help_text="Icon for the particular sidebar item."
    )
    url = models.CharField(
        max_length=2048,
        help_text="URL that the sidebar item points to.",
        blank=True,
        null=True
    )
    parent : Self = models.ForeignKey(
        to="self",
        null=True,
        blank=True,
        related_name="children",
        on_delete=models.CASCADE
    )
    is_folder = models.BooleanField(
        default=False
    )
    position = models.PositiveIntegerField(
        default=0,
        help_text="Position of the sidebar item among its siblings. Lower numbers appear first."
    )
    color = models.CharField(
        max_length=7,
        default="#bfdbfe",
        help_text="Hex color code for the sidebar item (e.g. #FF5733)."
    )

    def __str__(self):
        return f"{self.name} ({self.url})"
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

    @classmethod
    def ordered_for_parent(cls, sidebar: "Sidebar", parent: Self | None, exclude_id: int | None = None) -> list[Self]:
        queryset = cls.objects.filter(sidebar=sidebar, parent=parent).order_by("position", "id")
        if exclude_id is not None:
            queryset = queryset.exclude(pk=exclude_id)
        return list(queryset)

    def is_descendant_of(self, ancestor: Self) -> bool:
        current = self.parent
        while current is not None:
            if current.pk == ancestor.pk:
                return True
            current = current.parent
        return False

    def clean(self):
        errors: dict[str, str] = {}

        if self.parent and self.parent.is_folder == False:
            errors["parent"] = "Parent sidebar item must be a folder."
        
        if self.url and self.is_folder:
            errors["url"] = "Sidebar item cannot have a URL if it is a folder."
        
        if not self.url and not self.is_folder:
            errors["url"] = "Sidebar item must have a URL if it is not a folder."
        elif self.url and not is_internal_sidebar_url(self.url):
            try:
                EXTERNAL_URL_VALIDATOR(self.url)
            except ValidationError:
                errors["url"] = "Enter either a full http(s) URL or an internal path starting with /."

        if errors:
            raise ValidationError(errors)

        return super().clean()

    @classmethod
    def create_folder(cls, 
                      sidebar: "Sidebar", 
                      name: str, 
                      icon: str = DEFAULT_FOLDER_ICON, 
                      parent: Self | None = None, position: int = 0) -> Self:
        """Factory method to create a folder sidebar item. This method ensures that the created sidebar item is a folder and validates it before saving."""
        folder = cls(
            sidebar=sidebar,
            name=name,
            icon=icon,
            is_folder=True,
            parent=parent,
            position=position
        )
        folder.full_clean()
        folder.save()
        return folder
    
    @classmethod
    def create_link(cls,
                    sidebar: "Sidebar", 
                    name: str, 
                    url: str, 
                    icon: str = DEFAULT_LINK_ICON, 
                    parent: Self | None = None, position: int = 0) -> Self:
        """Factory method to create a link sidebar item. This method ensures that the created sidebar item is not a folder and validates it before saving."""
        link = cls(
            sidebar=sidebar,
            name=name,
            url=url,
            icon=icon,
            is_folder=False,
            parent=parent,
            position=position
        )
        link.full_clean()
        link.save()
        return link

    @property
    def is_internal_url(self) -> bool:
        """
        Checks whether it's a internal url. If it is, it will change the way things are being rendered when clicking on them in the sidebar.
        """
        return is_internal_sidebar_url(self.url)

    def move_to(self, parent: Self | None, position: int) -> None:
        if parent and parent.sidebar_id != self.sidebar_id:
            raise ValidationError({"parent": "Target parent must belong to the same sidebar."})

        if parent and not parent.is_folder:
            raise ValidationError({"parent": "Target parent must be a folder."})

        if parent and parent.pk == self.pk:
            raise ValidationError({"parent": "An item cannot be placed inside itself."})

        if parent and parent.is_descendant_of(self):
            raise ValidationError({"parent": "A folder cannot be moved into one of its descendants."})

        old_parent = self.parent
        old_parent_id = self.parent_id
        new_parent_id = parent.pk if parent else None

        new_siblings = self.__class__.ordered_for_parent(self.sidebar, parent, exclude_id=self.pk)
        adjusted_position = position
        if old_parent_id == new_parent_id and adjusted_position > self.position:
            adjusted_position -= 1

        bounded_position = max(0, min(adjusted_position, len(new_siblings)))
        new_siblings.insert(bounded_position, self)

        with transaction.atomic():
            if old_parent_id != new_parent_id:
                old_siblings = self.__class__.ordered_for_parent(self.sidebar, old_parent, exclude_id=self.pk)
                for index, sibling in enumerate(old_siblings):
                    sibling.position = index

                if old_siblings:
                    self.__class__.objects.bulk_update(old_siblings, ["position"])

            self.parent = parent
            for index, sibling in enumerate(new_siblings):
                if sibling.pk == self.pk:
                    sibling.parent = parent
                sibling.position = index

            self.__class__.objects.bulk_update(new_siblings, ["parent", "position"])
