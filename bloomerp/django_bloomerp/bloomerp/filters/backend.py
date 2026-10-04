"""DRF integration for the shared model filter manager."""

from django.db.models import QuerySet
from rest_framework.filters import BaseFilterBackend
from rest_framework.request import Request
from rest_framework.views import APIView

from bloomerp.filters.manager import ModelFilterManager


class ModelFilterBackend(BaseFilterBackend):
    def filter_queryset(
        self, request: Request, queryset: QuerySet, view: APIView
    ) -> QuerySet:
        """Apply shared filters while keeping private agent relations out of query input."""
        if queryset.model._meta.label_lower in {
            "bloomerp.aiconversation",
            "bloomerp.aimessage",
        }:
            from bloomerp.agents.api import filter_agent_api_queryset

            return filter_agent_api_queryset(request, queryset)
        return ModelFilterManager(queryset.model).filter(
            request.query_params,
            queryset=queryset,
        )
