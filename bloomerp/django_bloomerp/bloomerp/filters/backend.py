"""DRF integration for the shared model filter manager."""
from django.db.models import QuerySet
from rest_framework.filters import BaseFilterBackend
from rest_framework.request import Request

from bloomerp.filters.manager import ModelFilterManager


class ModelFilterBackend(BaseFilterBackend):
    def filter_queryset(self, request:Request, queryset:QuerySet, view):
        return ModelFilterManager(queryset.model).filter(
            request.query_params,
            queryset=queryset,
        )
