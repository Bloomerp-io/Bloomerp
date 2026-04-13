from collections.abc import Mapping

from rest_framework import viewsets, status
from django_filters import rest_framework as filters
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist

from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import BloomerpModelConfig
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

    def _get_bloomerp_config(self) -> BloomerpModelConfig | None:
        config = getattr(self.model, "bloomerp_config", None)
        if isinstance(config, BloomerpModelConfig):
            return config
        return None

    def _get_public_action_name(self, action: str | None = None) -> str:
        action_name = action or self.action or "list"
        if action_name == "retrieve":
            return "read"
        return action_name

    def _get_public_access_rules(self, action: str | None = None):
        config = self._get_bloomerp_config()
        if config is None:
            return []
        return config.get_public_access_rules(self._get_public_action_name(action))

    def _has_internal_access(self, permission_str: str) -> bool:
        manager = self._get_permission_manager()
        if getattr(manager.user, "is_superuser", False):
            return True
        if manager.is_anonymous or not self.model:
            return False
        return manager.has_global_permission(self.model, permission_str) or manager.has_row_level_access(
            self.model, permission_str
        )

    def _should_use_public_access(self, action: str | None = None) -> bool:
        if not self.model:
            return False
        if not self._get_public_access_rules(action):
            return False
        permission_str = self._get_permission_str(action)
        return not self._has_internal_access(permission_str)

    def _build_public_rule_kwargs(self, rule) -> dict:
        filter_kwargs: dict = {}
        for filter_rule in rule.filters:
            field_name = str(filter_rule.field or "").strip()
            if not field_name:
                return {}

            try:
                self.model._meta.get_field(field_name)
            except FieldDoesNotExist:
                return {}

            operator = str(filter_rule.operator or "exact").strip()
            if operator in {"", "exact"}:
                filter_key = field_name
            else:
                filter_key = f"{field_name}__{operator}"

            filter_kwargs[filter_key] = filter_rule.value

        return filter_kwargs

    def _get_public_queryset(self, action: str | None = None):
        queryset = self.model.objects.all()
        rules = self._get_public_access_rules(action)
        if not rules:
            return queryset.none()

        object_ids: set = set()
        unrestricted = False

        for rule in rules:
            filter_kwargs = self._build_public_rule_kwargs(rule)
            if rule.filters and not filter_kwargs:
                continue
            if not rule.filters:
                unrestricted = True
                break
            object_ids.update(
                queryset.filter(**filter_kwargs).values_list("pk", flat=True)
            )

        if unrestricted:
            return queryset
        if not object_ids:
            return queryset.none()
        return queryset.filter(pk__in=object_ids)

    def _get_public_accessible_field_names(self, action: str | None = None) -> set[str] | None:
        rules = self._get_public_access_rules(action)
        if not rules:
            return None

        allowed_fields: set[str] = set()
        for rule in rules:
            if rule.fields == "__all__":
                return None
            allowed_fields.update(rule.fields)
        return allowed_fields

    def _get_permission_str(self, action: str | None = None) -> str:
        action = action or self.action or "view"
        permission = self.action_permission_map.get(action, "view")
        return create_permission_str(self.model, permission)

    def _get_accessible_field_names(self, permission_str: str) -> set[str] | None:
        if self._should_use_public_access():
            return self._get_public_accessible_field_names()

        manager = self._get_permission_manager()
        if not self.model or getattr(manager.user, "is_superuser", False):
            return None

        content_type = ContentType.objects.get_for_model(self.model)
        accessible_fields = manager.get_accessible_fields(content_type, permission_str)
        return set(accessible_fields.values_list("field", flat=True))

    def get_permissions(self):
        if self._should_use_public_access():
            return [AllowAny()]
        return [permission() for permission in self.permission_classes]

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
        if self._should_use_public_access():
            return self._get_public_queryset()

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
