"""Generated-SDK-compatible record endpoints for document preparation."""

from typing import ClassVar

from bloomerp.api.document_signing import SIGNING_BUILDER_MODELS, SigningBuilderApiView
from bloomerp.router import router


@router.register(
    path="", route_type="api_detail", models=list(SIGNING_BUILDER_MODELS), override=True
)
class SigningBuilderDetailApiView(SigningBuilderApiView):
    """Read, update, and remove draft records without exposing signature execution."""

    actions: ClassVar[dict[str, str]] = {
        "get": "retrieve",
        "put": "update",
        "patch": "partial_update",
        "delete": "destroy",
    }
