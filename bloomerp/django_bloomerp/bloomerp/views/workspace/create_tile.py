from bloomerp.router import router
from bloomerp.views.view_mixins.wizard import WizardMixin
from django.views.generic import TemplateView
from bloomerp.views.mixins import HtmxMixin

@router.register(
    path="create-tile",
    name="Create Tile",
    description="Create a new tile for the workspace",
)
class CreateTileView(HtmxMixin, WizardMixin, TemplateView):
    template_name = "workspace_views/create_tile.html"
    