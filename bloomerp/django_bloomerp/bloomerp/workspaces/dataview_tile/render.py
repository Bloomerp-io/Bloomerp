from django.http import HttpRequest
from django.contrib.contenttypes.models import ContentType

from bloomerp.components.objects.dataview import data_view
from bloomerp.models.users.user import User
from bloomerp.services.user_services import get_user_list_view_preference
from bloomerp.workspaces.base import BaseTileRenderer
from bloomerp.workspaces.dataview_tile.model import DataViewTileConfig, build_preview_preference

class DataViewTileRenderer(BaseTileRenderer):

    @classmethod
    def render(cls, config: DataViewTileConfig, user:User) -> str:
        """
        Render the data view tile based on the provided configuration.

        Args:
            config (DataViewTileConfig): The configuration for the data view tile.

        Returns:
            str: The rendered HTML for the data view tile.
        """
        print(config)
        content_type = ContentType.objects.filter(id=config.content_type_id).first()
        

        request = HttpRequest()
        request.user = user
        request.method = "GET"


        return data_view(
            request, 
            content_type_id=config.content_type_id,
        ).content.decode("utf-8")

        



        