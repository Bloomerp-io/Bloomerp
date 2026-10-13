"""Compatibility redirect to the standard connection collection."""

from typing import Any
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.views import View
from bloomerp.router import router
from bloomerp.views.base import BaseBloomerpView


@router.register(
    path="communication/voip/", url_name="voip_connections", name="VoIP connections"
)
class VoIPConnectionsView(BaseBloomerpView, View):
    """Use the generated model workspace instead of a parallel management screen."""

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Preserve old bookmarks while exposing the model's configured actions and views."""
        return redirect("voip_connections_model")
