from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from django.contrib.contenttypes.models import ContentType
from django.db.models import Model, QuerySet
from rest_framework import serializers
from rest_framework import viewsets

from bloomerp.models.definition import BloomerpModelConfig
from bloomerp.permissions.compilers.base import BasePermissionCompiler
from bloomerp.permissions.compilers.django_q_permission_compiler import (
    DjangoQPermissionCompiler,
)
from bloomerp.permissions.compilers.python_permission_compiler import PythonPermissionCompiler
from bloomerp.permissions.definition import PermissionMatch
from bloomerp.permissions.manager import UserPolicyManager, create_permission_str
from bloomerp.models.application_field import ApplicationField
from bloomerp.filters.backend import ModelFilterBackend
from django_filters.rest_framework import DjangoFilterBackend



def _normalize_api_choice_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _normalize_api_choices(choices):
    if isinstance(choices, Mapping):
        choice_items = choices.items()
    else:
        choice_items = choices

    normalized_choices = []
    for choice in choice_items:
        if not isinstance(choice, (list, tuple)) or len(choice) != 2:
            normalized_choices.append(choice)
            continue

        value, label = choice
        if isinstance(label, (list, tuple)):
            normalized_choices.append((value, _normalize_api_choices(label)))
        else:
            normalized_choices.append((_normalize_api_choice_value(value), label))

    return normalized_choices


@dataclass
class NestingNode:
    relation_name: str
    fields: set[str] | None = field(default_factory=set)
    auto_pk: bool = True
    children: dict[str, "NestingNode"] = field(default_factory=dict)

    def merge_fields(self, incoming_fields: set[str] | None) -> None:
        if incoming_fields is None:
            self.fields = None
            return
        if self.fields is None:
            return
        self.fields.update(incoming_fields)


class ApiAccessResolver:
    action_permission_map = {
        "list": "view",
        "retrieve": "view",
        "read": "view",
        "create": "add",
        "update": "change",
        "partial_update": "change",
        "destroy": "delete",
        "bulk_create": "bulk_add",
    }

    def __init__(self, request):
        self.request = request
        self.permission_manager = UserPolicyManager(request.user)

    def _get_bloomerp_config(self, model: type[Model]) -> BloomerpModelConfig | None:
        config = getattr(model, "bloomerp_config", None)
        if isinstance(config, BloomerpModelConfig):
            return config
        return None

    def get_permission_action_name(self, action: str | None = None) -> str:
        action_name = str(action or "retrieve").strip().lower()
        return self.action_permission_map.get(action_name, "view")

    def get_public_action_name(self, action: str | None = None) -> str:
        """Return the legacy nesting action while access uses model permissions."""
        action_name = str(action or "retrieve").strip().lower()
        return "list" if action_name == "list" else "read"

    def get_permission_str(self, model: type[Model], action: str | None = None) -> str:
        return create_permission_str(model, self.get_permission_action_name(action))

    def get_config_access_rules(
        self,
        model: type[Model],
        *,
        authenticated: bool,
    ):
        config = self._get_bloomerp_config(model)
        if config is None:
            return []
        return config.get_api_access_rules(authenticated=authenticated)

    def get_anonymous_access_rules(self, model: type[Model]):
        config = self._get_bloomerp_config(model)
        if config is None or config.api_settings is None:
            return []
        return list(config.api_settings.access.anonymous)

    def _rule_grants_permission(self, rule, permission: str) -> bool:
        return any(
            BasePermissionCompiler.matches_requested_permissions(
                row_rule.permissions,
                [permission],
                match=PermissionMatch.ANY,
            )
            for row_rule in rule.row_permissions
        )

    def _filter_rules_for_action(self, rules, action: str | None = None):
        permission = self.get_permission_action_name(action)
        return [
            rule
            for rule in rules
            if self._rule_grants_permission(rule, permission)
        ]

    def get_applicable_access_rules(
        self,
        model: type[Model],
        action: str | None = None,
    ):
        authenticated = not self.permission_manager.is_anonymous
        rules = self.get_config_access_rules(
            model,
            authenticated=authenticated,
        )
        if authenticated:
            rules = [
                *self.permission_manager.get_access_rules(
                    model,
                    self.get_permission_action_name(action),
                ),
                *rules,
            ]
        return self._filter_rules_for_action(rules, action)

    def has_internal_access(self, model: type[Model], action: str | None = None) -> bool:
        if getattr(self.permission_manager.user, "is_superuser", False):
            return True
        if self.permission_manager.is_anonymous:
            return False
        permission_str = self.get_permission_str(model, action)
        return self.permission_manager.has_global_permission(
            model, permission_str
        ) or self.permission_manager.has_row_level_access(model, permission_str)

    def get_queryset(self, model: type[Model], action: str | None = None) -> QuerySet:
        queryset = model.objects.all()
        if getattr(self.permission_manager.user, "is_superuser", False):
            return queryset
        permission = self.get_permission_action_name(action)
        rules = self.get_applicable_access_rules(model, action)
        compilation = DjangoQPermissionCompiler(
            rules,
            user=self.request.user,
            model=model,
        ).compile(permission)
        return queryset.filter(compilation.row_filter).distinct()

    def get_accessible_field_names(
        self, model: type[Model], action: str | None = None
    ) -> set[str] | None:
        if getattr(self.permission_manager.user, "is_superuser", False):
            return None

        permission = self.get_permission_action_name(action)
        allowed_fields: set[str] = set()
        config_rules = self._filter_rules_for_action(
            self.get_config_access_rules(
                model,
                authenticated=not self.permission_manager.is_anonymous,
            ),
            action,
        )
        for rule in config_rules:
            wildcard_permissions = rule.field_permissions.get("__all__", [])
            if BasePermissionCompiler.matches_requested_permissions(
                wildcard_permissions,
                [permission],
                PermissionMatch.ANY,
            ):
                return None
            allowed_fields.update(
                field_name
                for field_name, permissions in rule.field_permissions.items()
                if field_name != "__all__"
                and BasePermissionCompiler.matches_requested_permissions(
                    permissions,
                    [permission],
                    PermissionMatch.ANY,
                )
            )
        if not self.permission_manager.is_anonymous and self.permission_manager.has_global_permission(
            model,
            permission,
        ):
            allowed_fields.update(
                self.permission_manager.get_accessible_fields(
                    model,
                    permission,
                ).values_list("field", flat=True)
            )
        rules = self.get_applicable_access_rules(model, action)
        compilation = DjangoQPermissionCompiler(
            rules,
            user=self.request.user,
            model=model,
        ).compile(permission)
        allowed_fields.update({
            application_field.field
            for application_fields in compilation.field_filters.values()
            for application_field in application_fields
        })
        return allowed_fields

    def candidate_matches(
        self,
        candidate: Model,
        action: str | None = None,
    ) -> bool:
        if getattr(self.permission_manager.user, "is_superuser", False):
            return True
        permission = self.get_permission_action_name(action)
        if not self.permission_manager.is_anonymous and self.permission_manager.has_global_permission(
            type(candidate),
            permission,
        ):
            return True
        rules = self.get_applicable_access_rules(type(candidate), action)
        evaluator = PythonPermissionCompiler(
            rules,
            user=self.request.user,
            model=type(candidate),
        ).compile(permission)
        return evaluator.matches(candidate)

    def model_allows_anonymous(
        self,
        model: type[Model],
        action: str | None = None,
    ) -> bool:
        return bool(
            self._filter_rules_for_action(
                self.get_anonymous_access_rules(model),
                action,
            )
        )

    def has_config_access(
        self,
        model: type[Model],
        action: str | None = None,
    ) -> bool:
        authenticated = not self.permission_manager.is_anonymous
        return bool(
            self._filter_rules_for_action(
                self.get_config_access_rules(
                    model,
                    authenticated=authenticated,
                ),
                action,
            )
        )

    def has_action_access(
        self,
        model: type[Model],
        action: str | None = None,
    ) -> bool:
        if getattr(self.permission_manager.user, "is_superuser", False):
            return True
        if self.has_internal_access(model, action):
            return True
        return bool(self.get_applicable_access_rules(model, action))

    def has_read_contract(self, model: type[Model], action: str | None = None) -> bool:
        return self.has_action_access(model, action)


def build_nesting_tree(model: type[Model], rules: list) -> dict[str, NestingNode]:
    tree: dict[str, NestingNode] = {}

    for rule in rules:
        path = str(getattr(rule, "for_field", "") or "").strip()
        if not path:
            continue

        parts = [part for part in path.split(".") if part]
        if not parts:
            continue

        current_model = model
        current_tree = tree
        node: NestingNode | None = None

        for index, part in enumerate(parts):
            relation = resolve_relation(current_model, part)
            if relation is None:
                node = None
                break

            node = current_tree.get(part)
            if node is None:
                node = NestingNode(relation_name=part)
                current_tree[part] = node

            if index == len(parts) - 1:
                configured_fields = getattr(rule, "fields", ["__all__"])
                if "__all__" in configured_fields:
                    node.merge_fields(None)
                else:
                    node.merge_fields(
                        {
                            field_name
                            for field_name in configured_fields
                            if field_name != "__all__"
                        }
                    )
                node.auto_pk = node.auto_pk or bool(getattr(rule, "auto_pk", True))

            current_model = relation.related_model
            current_tree = node.children

        if node is None:
            continue

    return tree


def resolve_relation(model: type[Model], relation_name: str):
    for field in model._meta.get_fields():
        accessor_name = getattr(field, "get_accessor_name", lambda: None)()
        if field.name == relation_name or accessor_name == relation_name:
            if not getattr(field, "is_relation", False):
                return None
            return field
    return None


def apply_queryset_nesting(
    queryset: QuerySet,
    model: type[Model],
    request,
    action: str | None = None,
) -> QuerySet:
    resolver = ApiAccessResolver(request)
    config = resolver._get_bloomerp_config(model)
    if config is None or getattr(config, "api_settings", None) is None:
        return queryset

    rules = getattr(config.api_settings, "get_nesting_rules", lambda _action: [])(
        resolver.get_public_action_name(action)
    )
    if not rules:
        return queryset

    select_related_paths: set[str] = set()
    prefetch_related_paths: set[str] = set()

    for rule in rules:
        path = str(getattr(rule, "for_field", "") or "").strip()
        if not path:
            continue

        current_model = model
        segments: list[str] = []
        valid = True
        for part in [segment for segment in path.split(".") if segment]:
            relation = resolve_relation(current_model, part)
            if relation is None:
                valid = False
                break

            segments.append(part)
            joined = "__".join(segments)
            if getattr(relation, "many_to_one", False) or getattr(
                relation, "one_to_one", False
            ):
                select_related_paths.add(joined)
            else:
                prefetch_related_paths.add(joined)

            current_model = relation.related_model

        if not valid:
            continue

    if select_related_paths:
        queryset = queryset.select_related(*sorted(select_related_paths))
    if prefetch_related_paths:
        queryset = queryset.prefetch_related(*sorted(prefetch_related_paths))
    return queryset

def generate_serializer(model:Model) -> type[serializers.ModelSerializer]:
    '''
    Dynamically generate a serializer class for a given model.
    '''

    # Dynamically create a Meta class
    meta_class = type('Meta', (object,), {
        'model': model,
        'fields': '__all__',
    })

    class GeneratedSerializer(serializers.ModelSerializer):
        Meta = meta_class

        def build_standard_field(self, field_name, model_field):
            field_class, field_kwargs = super().build_standard_field(
                field_name,
                model_field,
            )

            if "choices" in field_kwargs:
                field_kwargs["choices"] = _normalize_api_choices(
                    field_kwargs["choices"]
                )

            return field_class, field_kwargs

        def _get_serializer_action(self) -> str:
            view = self.context.get("view")
            return getattr(view, "action", None) or "retrieve"

        def _get_nesting_action(self) -> str:
            action_name = self._get_serializer_action()
            return ApiAccessResolver(self.context["request"]).get_public_action_name(
                action_name
            )

        def _get_nesting_tree(self) -> dict:
            if "bloomerp_nesting_tree" in self.context:
                return self.context["bloomerp_nesting_tree"] or {}

            request = self.context.get("request")
            if request is None:
                return {}

            config = getattr(self.Meta.model, "bloomerp_config", None)
            api_settings = getattr(config, "api_settings", None)
            if api_settings is None:
                return {}

            rules = api_settings.get_nesting_rules(self._get_nesting_action())
            return build_nesting_tree(self.Meta.model, rules)

        def _get_requested_nested_fields(self) -> set[str] | None:
            nested_fields = self.context.get("bloomerp_nested_fields")
            if nested_fields is None:
                return None
            return set(nested_fields)

        def _should_include_nested_relation(
            self,
            relation_name: str,
            node,
            allowed_fields: set[str] | None,
            requested_fields: set[str] | None,
        ) -> bool:
            if allowed_fields is not None and relation_name not in allowed_fields:
                return False
            if requested_fields is not None and relation_name not in requested_fields:
                return False
            return True

        def _serialize_nested_relation(self, instance, relation_name: str, node):
            request = self.context.get("request")
            if request is None:
                return None, False

            relation = resolve_relation(self.Meta.model, relation_name)
            if relation is None:
                return None, False

            resolver = ApiAccessResolver(request)
            related_model = relation.related_model
            if related_model is None or not resolver.has_read_contract(
                related_model, "retrieve"
            ):
                return None, False

            nested_context = dict(self.context)
            nested_context["bloomerp_nesting_tree"] = node.children
            nested_context["bloomerp_nested_fields"] = (
                None if node.fields is None else set(node.fields)
            )
            nested_context["bloomerp_auto_pk"] = node.auto_pk

            if getattr(relation, "many_to_one", False) or getattr(
                relation, "one_to_one", False
            ):
                related_instance = getattr(instance, relation_name, None)
                if related_instance is None:
                    return None, True

                if not resolver.get_queryset(related_model, "retrieve").filter(
                    pk=related_instance.pk
                ).exists():
                    return None, False

                serializer = generate_serializer(related_model)(
                    related_instance,
                    context=nested_context,
                )
                nested_data = serializer.data
                if not nested_data:
                    return None, False
                return nested_data, True

            related_manager = getattr(instance, relation_name, None)
            if related_manager is None:
                return [], True

            queryset = related_manager.all()
            accessible_queryset = resolver.get_queryset(
                related_model, "retrieve"
            ).filter(pk__in=queryset.values_list("pk", flat=True))
            serializer = generate_serializer(related_model)(
                accessible_queryset,
                many=True,
                context=nested_context,
            )
            return serializer.data, True

        def to_representation(self, instance):
            data = super().to_representation(instance)

            request = self.context.get("request")
            if request is None:
                return data

            resolver = ApiAccessResolver(request)
            allowed_fields = resolver.get_accessible_field_names(
                self.Meta.model,
                self._get_serializer_action(),
            )
            requested_fields = self._get_requested_nested_fields()

            if requested_fields is not None:
                if getattr(self.Meta.model._meta.pk, "name", None) and self.context.get(
                    "bloomerp_auto_pk", True
                ):
                    requested_fields.add(self.Meta.model._meta.pk.name)
                data = {
                    key: value
                    for key, value in data.items()
                    if key in requested_fields
                }

            if allowed_fields is not None:
                data = {
                    key: value
                    for key, value in data.items()
                    if key in allowed_fields
                }

            for relation_name, node in self._get_nesting_tree().items():
                if not self._should_include_nested_relation(
                    relation_name,
                    node,
                    allowed_fields,
                    requested_fields,
                ):
                    continue

                nested_data, include_field = self._serialize_nested_relation(
                    instance, relation_name, node
                )
                if include_field:
                    data[relation_name] = nested_data
                else:
                    data.pop(relation_name, None)

            return data

    GeneratedSerializer.__name__ = f"{model.__name__}Serializer"
    return GeneratedSerializer


def generate_model_viewset_class(
        model:Model,
        serializer:serializers.ModelSerializer,
        base_viewset:viewsets.ModelViewSet
        ):
    '''
    Dynamically generate a viewset class for a given
    model.
    '''

    Class = type(f'{model.__name__}ViewSet', (base_viewset,), {
        'model': model,
        'serializer_class': serializer,
        'filter_backends': (ModelFilterBackend, *tuple(
            backend for backend in getattr(base_viewset, 'filter_backends', ())
            if backend is not ModelFilterBackend
            and not issubclass(backend, DjangoFilterBackend)
        )),
    })
    
    return Class
