"""Generated-SDK-compatible collection endpoints for document preparation."""

from typing import ClassVar

from bloomerp.api.document_signing import SIGNING_BUILDER_MODELS, SigningBuilderApiView
from bloomerp.router import router


@router.register(
    path="", route_type="api_model", models=list(SIGNING_BUILDER_MODELS), override=True
)
class SigningBuilderListApiView(SigningBuilderApiView):
    """List and create draft records under ordinary model and file permissions."""

    actions: ClassVar[dict[str, str]] = {"get": "list", "post": "create"}
