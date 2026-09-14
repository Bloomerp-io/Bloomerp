from collections.abc import Mapping

from django.db import transaction
from django.db.models import Model
from rest_framework import status, viewsets
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from bloomerp.filters.backend import ModelFilterBackend

from bloomerp.api.authentication_classes import BloomerpApiKeyAuthentication
from bloomerp.models.definition import BloomerpModelConfig
from bloomerp.utils.api import ApiAccessResolver, apply_queryset_nesting


AUTHENTICATION_CLASSES = (
    BloomerpApiKeyAuthentication,
    SessionAuthentication,
    BasicAuthentication,
)


class BloomerpModelViewSet(viewsets.ModelViewSet):
    """DRF adapter around BloomERP's shared access-rule compilers."""

    model: type[Model] | None = None
    queryset = None
    serializer_class = None
    authentication_classes = AUTHENTICATION_CLASSES
    filter_backends = (ModelFilterBackend,)
    permission_classes = (IsAuthenticated,)
    action_permission_map = ApiAccessResolver.action_permission_map

    def _get_bloomerp_config(self) -> BloomerpModelConfig | None:
        config = getattr(self.model, "bloomerp_config", None)
        return config if isinstance(config, BloomerpModelConfig) else None

    def _get_access_resolver(self) -> ApiAccessResolver:
        return ApiAccessResolver(self.request)

    def _get_permission_str(self, action: str | None = None) -> str:
        return self._get_access_resolver().get_permission_str(
            self.model,
            action or self.action,
        )

    def get_permissions(self):
        if self.model and self._get_access_resolver().model_allows_anonymous(
            self.model,
            self.action,
        ):
            return [AllowAny()]
        return [permission() for permission in self.permission_classes]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.model.objects.none()
        queryset = self._get_access_resolver().get_queryset(
            self.model,
            self.action,
        )
        return apply_queryset_nesting(
            queryset,
            self.model,
            self.request,
            self.action,
        )

    def get_serializer_class(self):
        return self.serializer_class

    def _get_accessible_field_names(self, action: str | None = None) -> set[str] | None:
        return self._get_access_resolver().get_accessible_field_names(
            self.model,
            action or self.action,
        )

    def _apply_field_permissions(self, serializer, action: str | None = None):
        allowed_fields = self._get_accessible_field_names(action)
        if allowed_fields is None:
            return serializer

        target = serializer.child if hasattr(serializer, "child") else serializer
        for field_name in list(target.fields):
            if field_name not in allowed_fields:
                target.fields.pop(field_name)
        return serializer

    def _get_write_payload_items(self) -> list[tuple[int | None, Mapping]]:
        if isinstance(self.request.data, list):
            return [
                (index, item)
                for index, item in enumerate(self.request.data)
                if isinstance(item, Mapping)
            ]
        if isinstance(self.request.data, Mapping):
            return [(None, self.request.data)]
        return []

    def _enforce_write_field_permissions(self, action: str):
        allowed_fields = self._get_accessible_field_names(action)
        if allowed_fields is None:
            return

        for index, payload in self._get_write_payload_items():
            denied = sorted(set(payload) - allowed_fields)
            if not denied:
                continue
            suffix = "" if index is None else f" at index {index}"
            raise PermissionDenied(
                f"Permission denied for fields{suffix}: {', '.join(denied)}"
            )

    def _build_candidate(self, validated_data: Mapping, instance=None) -> Model:
        values = {}
        if instance is not None:
            for field in self.model._meta.fields:
                values[field.name] = getattr(instance, field.name)
        values.update(validated_data)

        candidate = self.model(**values)
        user = getattr(self.request, "user", None)
        if user is not None and not user.is_anonymous:
            if hasattr(candidate, "created_by") and not getattr(candidate, "created_by", None):
                candidate.created_by = user
            if hasattr(candidate, "updated_by"):
                candidate.updated_by = user
        return candidate

    def _enforce_row_permissions(self, serializer, action: str, instance=None):
        resolver = self._get_access_resolver()
        if instance is not None and resolver.has_internal_access(self.model, action):
            return
        validated_items = (
            list(serializer.validated_data)
            if hasattr(serializer, "child")
            else [serializer.validated_data]
        )
        for validated_data in validated_items:
            candidate = self._build_candidate(validated_data, instance)
            if not resolver.candidate_matches(candidate, action):
                raise PermissionDenied(
                    "You do not have permission to use this object with these values."
                )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            self._apply_field_permissions(serializer, "list")
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        self._apply_field_permissions(serializer, "list")
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object())
        self._apply_field_permissions(serializer, "retrieve")
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        is_many = isinstance(request.data, list)
        access_action = "create"
        field_action = access_action
        resolver = self._get_access_resolver()
        if is_many and not resolver.has_config_access(self.model, access_action):
            field_action = "bulk_create"
        self._enforce_write_field_permissions(field_action)

        serializer = self.get_serializer(data=request.data, many=is_many)
        serializer.is_valid(raise_exception=True)
        self._enforce_row_permissions(serializer, field_action)

        with transaction.atomic():
            self.perform_create(serializer)

        output = self.get_serializer(serializer.instance, many=is_many)
        self._apply_field_permissions(output, field_action)
        headers = self.get_success_headers(output.data)
        return Response(output.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        action = "partial_update" if partial else "update"
        instance = self.get_object()
        self._enforce_write_field_permissions(action)

        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)
        self._enforce_row_permissions(serializer, action, instance)
        self.perform_update(serializer)

        output = self.get_serializer(serializer.instance)
        self._apply_field_permissions(output, action)
        return Response(output.data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)
