from django.db import models
from django.conf import settings


class Sidebar(models.Model):
    """
    A sidebar configuration for a particular user. Each user can have multiple sidebar configurations, as they might want to switch between different sidebar setups for different contexts. 
    """
    class Meta:
        db_table = "bloomerp_sidebar"

    user = models.ForeignKey(
        to=settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sidebars"
    )
    selected = models.BooleanField(
        default=False
    )
    name= models.CharField(
        max_length=255,
        help_text="Name of the sidebar configuration.",
        default="Default"
    )

    def __str__(self):
        return f"{self.name} ({self.user})"
    
    @property
    def items(self):
        from bloomerp.models.workspaces.sidebar_item import SidebarItem

        return SidebarItem.objects.filter(sidebar=self).order_by("position")
    
    @property
    def root_items(self):
        from bloomerp.models.workspaces.sidebar_item import SidebarItem

        return SidebarItem.objects.filter(sidebar=self, parent=None).order_by("position")

    def select(self) -> None:
        self.__class__.objects.filter(user=self.user, selected=True).exclude(pk=self.pk).update(selected=False)
        if not self.selected:
            self.selected = True
            self.save(update_fields=["selected"])
