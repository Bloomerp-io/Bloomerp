from collections.abc import Mapping

from rest_framework import viewsets, status
from django_filters import rest_framework as filters
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist
from django.db.models import Model, Q

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

    def _get_user_access_rules(self, action: str | None = None):
        config = self._get_bloomerp_config()
        if config is None:
            return []
        return config.get_user_access_rules(self.action_permission_map.get(action or self.action or "list", "view"))

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
        config = self._get_bloomerp_config()
        if config is not None and not getattr(
            getattr(config, "api_settings", None),
            "public_access_for_authenticated_fallback",
            True,
        ):
            return bool(getattr(self.request, "user", None) and self.request.user.is_anonymous)
        permission_str = self._get_permission_str(action)
        return not self._has_internal_access(permission_str)

    def _should_use_user_access(self, action: str | None = None) -> bool:
        if not self.model:
            return False

        manager = self._get_permission_manager()
        if manager.is_anonymous:
            return False

        if not self._get_user_access_rules(action):
            return False

        permission_str = self._get_permission_str(action)
        return not self._has_internal_access(permission_str)

    def _build_public_rule_q(self, rule) -> Q | None:
        rule_q = Q()
        for filter_rule in rule.filters:
            field_name = str(filter_rule.field or "").strip()
            if not field_name:
                return None

            try:
                self.model._meta.get_field(field_name)
            except FieldDoesNotExist:
                return None

            operator = str(filter_rule.get_lookup_operator() or "").strip().lower()
            if operator == "ne":
                rule_q &= ~Q(**{field_name: filter_rule.value})
                continue

            if operator in {"", "exact"}:
                filter_key = field_name
            else:
                filter_key = f"{field_name}__{operator}"

            rule_q &= Q(**{filter_key: filter_rule.value})

        return rule_q

    def _normalize_user_access_path(self, field_path: str | None) -> str:
        return str(field_path or "").replace(".", "__").strip("_")

    def _build_user_rule_q(self, rule) -> Q | None:
        through_field = self._normalize_user_access_path(getattr(rule, "through_field", ""))
        if not through_field:
            return None

        rule_q = Q(**{through_field: self.request.user})
        for filter_rule in getattr(rule, "filters", []):
            field_name = self._normalize_user_access_path(filter_rule.field)
            if not field_name:
                return None

            operator = str(filter_rule.get_lookup_operator() or "").strip().lower()
            if operator == "ne":
                rule_q &= ~Q(**{field_name: filter_rule.value})
                continue

            if operator in {"", "exact"}:
                filter_key = field_name
            else:
                filter_key = f"{field_name}__{operator}"

            rule_q &= Q(**{filter_key: filter_rule.value})

        return rule_q

    def _get_public_queryset(self, action: str | None = None):
        queryset = self.model.objects.all()
        rules = self._get_public_access_rules(action)
        if not rules:
            return queryset.none()

        object_ids: set = set()
        unrestricted = False

        for rule in rules:
            rule_q = self._build_public_rule_q(rule)
            if rule.filters and rule_q is None:
                continue
            if not rule.filters:
                unrestricted = True
                break
            object_ids.update(
                queryset.filter(rule_q).values_list("pk", flat=True)
            )

        if unrestricted:
            return queryset
        if not object_ids:
            return queryset.none()
        return queryset.filter(pk__in=object_ids)

    def _get_user_queryset(self, action: str | None = None):
        queryset = self.model.objects.all()
        rules = self._get_user_access_rules(action)
        if not rules:
            return queryset.none()

        object_ids: set = set()
        for rule in rules:
            rule_q = self._build_user_rule_q(rule)
            if rule_q is None:
                continue
            object_ids.update(
                queryset.filter(rule_q).values_list("pk", flat=True)
            )

        if not object_ids:
            return queryset.none()
        return queryset.filter(pk__in=object_ids)

    def _get_public_accessible_field_names(self, action: str | None = None) -> set[str] | None:
        rules = self._get_public_access_rules(action)
        if not rules:
            return None

        public_action = self._get_public_action_name(action)
        allowed_fields: set[str] = set()
        for rule in rules:
            rule_fields = rule.get_accessible_fields(public_action)
            if rule_fields is None:
                return None
            allowed_fields.update(rule_fields)
        return allowed_fields

    def _get_user_accessible_field_names(self, action: str | None = None) -> set[str] | None:
        rules = self._get_user_access_rules(action)
        if not rules:
            return set()

        permission_action = self.action_permission_map.get(action or self.action or "list", "view")
        allowed_fields: set[str] = set()

        for rule in rules:
            field_actions = getattr(rule, "field_actions", {}) or {}
            if not isinstance(field_actions, dict):
                continue

            wildcard_actions = field_actions.get("__all__")
            if wildcard_actions == "__all__" or (
                isinstance(wildcard_actions, list) and permission_action in wildcard_actions
            ):
                return None

            for field_name, actions in field_actions.items():
                if field_name == "__all__":
                    continue
                if actions == "__all__" or (
                    isinstance(actions, list) and permission_action in actions
                ):
                    allowed_fields.add(field_name)

        return allowed_fields

    def _get_permission_str(self, action: str | None = None) -> str:
        action = action or self.action or "view"
        permission = self.action_permission_map.get(action, "view")
        return create_permission_str(self.model, permission)

    def _get_accessible_field_names(self, permission_str: str, action: str | None = None) -> set[str] | None:
        if self._should_use_user_access(action):
            return self._get_user_accessible_field_names(action)

        if self._should_use_public_access(action):
            return self._get_public_accessible_field_names(action)

        manager = self._get_permission_manager()
        if not self.model or getattr(manager.user, "is_superuser", False):
            return None

        content_type = ContentType.objects.get_for_model(self.model)
        accessible_fields = manager.get_accessible_fields(content_type, permission_str)
        return set(accessible_fields.values_list("field", flat=True))

    def get_permissions(self):
        if self._should_use_user_access():
            return [IsAuthenticated()]
        if self._should_use_public_access():
            return [AllowAny()]
        return [permission() for permission in self.permission_classes]

    def _apply_field_permissions(self, serializer, permission_str: str, action: str | None = None):
        allowed_fields = self._get_accessible_field_names(permission_str, action)
        if allowed_fields is None:
            return serializer

        target = serializer.child if hasattr(serializer, "child") else serializer
        for field_name in list(target.fields.keys()):
            if field_name not in allowed_fields:
                target.fields.pop(field_name)
        return serializer

    def _enforce_write_field_permissions(self, permission_str: str, action: str | None = None):
        if self._should_use_user_access(action):
            allowed_fields = self._get_user_accessible_field_names(action)
            if allowed_fields is None:
                return

            if not isinstance(self.request.data, Mapping):
                return

            denied_fields = [
                field_name
                for field_name in self.request.data.keys()
                if field_name not in allowed_fields
            ]
            if denied_fields:
                denied = ", ".join(sorted(denied_fields))
                raise PermissionDenied(f"Permission denied for fields: {denied}")
            return

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

    def _resolve_candidate_value(self, candidate: Model, field_path: str):
        current = candidate
        for part in [segment for segment in self._normalize_user_access_path(field_path).split("__") if segment]:
            if current is None:
                return None
            try:
                current = getattr(current, part)
            except (AttributeError, FieldDoesNotExist):
                return None
        return current

    def _normalize_compare_value(self, value):
        if isinstance(value, Model):
            return getattr(value, "pk", None)
        return value

    def _matches_filter_rule(self, candidate: Model, filter_rule) -> bool:
        actual = self._resolve_candidate_value(candidate, filter_rule.field)
        expected = filter_rule.value
        operator = str(filter_rule.get_lookup_operator() or "").strip().lower()

        normalized_actual = self._normalize_compare_value(actual)
        normalized_expected = self._normalize_compare_value(expected)

        if operator in {"", "exact"}:
            return normalized_actual == normalized_expected
        if operator == "gte":
            return normalized_actual is not None and normalized_actual >= normalized_expected
        if operator == "gt":
            return normalized_actual is not None and normalized_actual > normalized_expected
        if operator == "lte":
            return normalized_actual is not None and normalized_actual <= normalized_expected
        if operator == "lt":
            return normalized_actual is not None and normalized_actual < normalized_expected
        if operator == "contains":
            return str(normalized_expected) in str(normalized_actual)
        if operator == "icontains":
            return str(normalized_expected).lower() in str(normalized_actual).lower()
        if operator == "in":
            expected_values = normalized_expected
            if isinstance(expected_values, str):
                expected_values = [item.strip() for item in expected_values.split(",") if item.strip()]
            expected_values = expected_values or []
            return normalized_actual in [self._normalize_compare_value(value) for value in expected_values]
        if operator == "isnull":
            expected_bool = normalized_expected
            if isinstance(expected_bool, str):
                expected_bool = expected_bool.lower() in {"true", "1", "yes"}
            return (normalized_actual is None) is bool(expected_bool)
        if operator == "ne":
            return normalized_actual != normalized_expected

        return False

    def _build_candidate_data(self, serializer, instance=None) -> dict:
        candidate_data = {}
        if instance is not None:
            for field in self.model._meta.fields:
                candidate_data[field.name] = getattr(instance, field.name)

        candidate_data.update(serializer.validated_data)
        return candidate_data

    def _candidate_matches_user_rule(self, candidate: Model, rule) -> bool:
        through_value = self._resolve_candidate_value(candidate, getattr(rule, "through_field", ""))
        if self._normalize_compare_value(through_value) != self._normalize_compare_value(self.request.user):
            return False

        for filter_rule in getattr(rule, "filters", []):
            if not self._matches_filter_rule(candidate, filter_rule):
                return False

        return True

    def _enforce_user_row_permissions(self, serializer, action: str | None = None, instance=None):
        if not self._should_use_user_access(action):
            return

        candidate = self.model(**self._build_candidate_data(serializer, instance))
        if hasattr(candidate, "created_by") and not getattr(candidate, "created_by", None):
            candidate.created_by = self.request.user
        if hasattr(candidate, "updated_by"):
            candidate.updated_by = self.request.user

        for rule in self._get_user_access_rules(action):
            if self._candidate_matches_user_rule(candidate, rule):
                return

        raise PermissionDenied("You do not have permission to use this object with these values.")

    def get_queryset(self):
        if self._should_use_user_access():
            return self._get_user_queryset()

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
            self._apply_field_permissions(serializer, permission_str, "list")
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        self._apply_field_permissions(serializer, permission_str, "list")
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        permission_str = self._get_permission_str("retrieve")
        self._apply_field_permissions(serializer, permission_str, "retrieve")
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        permission_str = self._get_permission_str("create")
        self._enforce_write_field_permissions(permission_str, "create")

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self._enforce_user_row_permissions(serializer, "create")
        self.perform_create(serializer)

        headers = self.get_success_headers(serializer.data)
        output_serializer = self.get_serializer(serializer.instance)
        self._apply_field_permissions(output_serializer, permission_str, "create")
        return Response(output_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        permission_str = self._get_permission_str("partial_update" if partial else "update")
        action_name = "partial_update" if partial else "update"
        self._enforce_write_field_permissions(permission_str, action_name)

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self._enforce_user_row_permissions(serializer, action_name, instance)
        self.perform_update(serializer)

        output_serializer = self.get_serializer(serializer.instance)
        self._apply_field_permissions(output_serializer, permission_str, action_name)
        return Response(output_serializer.data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)
