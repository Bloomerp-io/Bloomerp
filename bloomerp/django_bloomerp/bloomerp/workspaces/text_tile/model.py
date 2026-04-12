from typing import Self

from pydantic import BaseModel

from bloomerp.workspaces.base import (
    BaseTileConfig,
    TileOperationDefinition,
    TileOperationHandler,
    TileOperationHandlerRespone,
)


class TextTileConfig(BaseTileConfig):
    markdown: str = ""

    @classmethod
    def get_default(cls) -> Self:
        return cls(markdown="")

    @classmethod
    def get_operation(cls, operation: str) -> TileOperationDefinition:
        return {
            "update_markdown": TileOperationDefinition(
                validation_model=UpdateMarkdownOperation,
                handler=UpdateMarkdownHandler,
            ),
        }[operation]


class UpdateMarkdownOperation(BaseModel):
    markdown: str = ""


class UpdateMarkdownHandler(TileOperationHandler):
    @staticmethod
    def handle(config: TextTileConfig, data: UpdateMarkdownOperation) -> TileOperationHandlerRespone:
        config.markdown = data.markdown
        return TileOperationHandlerRespone(config=config, message="")
