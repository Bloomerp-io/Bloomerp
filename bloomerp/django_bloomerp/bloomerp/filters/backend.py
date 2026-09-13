"""DRF integration for the shared model filter manager."""
from rest_framework.filters import BaseFilterBackend

from bloomerp.filters.manager import ModelFilterManager


class ModelFilterBackend(BaseFilterBackend):
    def filter_queryset(self, request, queryset, view):
        return ModelFilterManager(queryset.model).filter(
            request.query_params,
            queryset=queryset,
        )
