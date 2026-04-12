from collections.abc import Mapping

from rest_framework import viewsets, status
from django_filters import rest_framework as filters
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from django.contrib.contenttypes.models import ContentType

from bloomerp.models.application_field import ApplicationField
from bloomerp.services.permission_services import (
    UserPermissionManager,
    create_permission_str,
)

class BloomerpModelViewSet(viewsets.ModelViewSet):
    # The model will be injected dynamically when the viewset is initialized
    queryset = None
    serializer_class = None
    filter_backends = (filters.DjangoFilterBackend,)
    filterset_fields = '__all__'
    permission_classes = (IsAuthenticated,)
    action_permission_map = {
        "list": "view",
        "retrieve": "view",
        "create": "add",
        "update": "change",
        "partial_update": "change",
        "destroy": "delete",
    }

    def _get_permission_manager(self) -> UserPermissionManager:
        return UserPermissionManager(self.request.user)

    def _get_permission_str(self, action: str | None = None) -> str:
        action = action or self.action or "view"
        permission = self.action_permission_map.get(action, "view")
        return create_permission_str(self.model, permission)

    def _get_accessible_field_names(self, permission_str: str) -> set[str] | None:
        manager = self._get_permission_manager()
        if not self.model or getattr(manager.user, "is_superuser", False):
            return None

        content_type = ContentType.objects.get_for_model(self.model)
        accessible_fields = manager.get_accessible_fields(content_type, permission_str)
        return set(accessible_fields.values_list("field", flat=True))

    def _apply_field_permissions(self, serializer, permission_str: str):
        allowed_fields = self._get_accessible_field_names(permission_str)
        if allowed_fields is None:
            return serializer

        target = serializer.child if hasattr(serializer, "child") else serializer
        for field_name in list(target.fields.keys()):
            if field_name not in allowed_fields:
                target.fields.pop(field_name)
        return serializer

    def _enforce_write_field_permissions(self, permission_str: str):
        manager = self._get_permission_manager()
        if getattr(manager.user, "is_superuser", False):
            return

        if not isinstance(self.request.data, Mapping):
            return

        denied_fields: list[str] = []
        for field_name in self.request.data.keys():
            application_field = ApplicationField.get_by_field(self.model, field_name)
            if not application_field:
                continue
            if not manager.has_field_permission(application_field, permission_str):
                denied_fields.append(field_name)

        if denied_fields:
            denied = ", ".join(sorted(denied_fields))
            raise PermissionDenied(f"Permission denied for fields: {denied}")

    def get_queryset(self):
        permission_str = self._get_permission_str()
        manager = self._get_permission_manager()
        return manager.get_queryset(self.model, permission_str)

    def get_serializer_class(self):
        return self.serializer_class

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        permission_str = self._get_permission_str("list")

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            self._apply_field_permissions(serializer, permission_str)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        self._apply_field_permissions(serializer, permission_str)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        permission_str = self._get_permission_str("retrieve")
        self._apply_field_permissions(serializer, permission_str)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        permission_str = self._get_permission_str("create")
        self._enforce_write_field_permissions(permission_str)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        headers = self.get_success_headers(serializer.data)
        output_serializer = self.get_serializer(serializer.instance)
        self._apply_field_permissions(output_serializer, permission_str)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        permission_str = self._get_permission_str("partial_update" if partial else "update")
        self._enforce_write_field_permissions(permission_str)

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        output_serializer = self.get_serializer(serializer.instance)
        self._apply_field_permissions(output_serializer, permission_str)
        return Response(output_serializer.data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)
