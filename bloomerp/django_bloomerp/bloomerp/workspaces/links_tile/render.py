from django.http import HttpRequest

from bloomerp.workspaces.base import BaseTileRenderer
from bloomerp.utils.navigation import supports_main_content_navigation
from bloomerp.workspaces.links_tile.model import LinkTileConfig, _iter_links
from bloomerp.workspaces.utils import UserParameterResolver


class LinksTileRenderer(BaseTileRenderer):
    template_name = "cotton/features/workspaces/tiles/link.html"

    @classmethod
    def render(cls, config: LinkTileConfig, request: HttpRequest) -> str:
        """Resolve nested link parameters and enable supported HTMX destinations."""
        rendered_config = config.model_copy(deep=True)
        resolver = UserParameterResolver(request.user)
        for link in _iter_links(rendered_config.links):
            link.url = resolver.resolve(link.url)
            link.is_internal = supports_main_content_navigation(link.url)

        return cls.render_to_string(
            {
                "config": rendered_config
            }
        )
