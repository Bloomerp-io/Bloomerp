from __future__ import annotations

from dataclasses import dataclass, field

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist
from django.db.models import Model, Q, QuerySet
from rest_framework import serializers
from rest_framework import viewsets

from bloomerp.models.definition import BloomerpModelConfig
from bloomerp.services.permission_services import (
    UserPermissionManager,
    create_permission_str,
)
from bloomerp.utils.filters import dynamic_filterset_factory


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
    }

    def __init__(self, request):
        self.request = request
        self.permission_manager = UserPermissionManager(request.user)

    def _get_bloomerp_config(self, model: type[Model]) -> BloomerpModelConfig | None:
        config = getattr(model, "bloomerp_config", None)
        if isinstance(config, BloomerpModelConfig):
            return config
        return None

    def get_public_action_name(self, action: str | None = None) -> str:
        action_name = str(action or "list").strip().lower()
        if action_name == "retrieve":
            return "read"
        if action_name not in {"list", "read"}:
            return "read"
        return action_name

    def get_permission_action_name(self, action: str | None = None) -> str:
        action_name = str(action or "retrieve").strip().lower()
        return self.action_permission_map.get(action_name, "view")

    def get_permission_str(self, model: type[Model], action: str | None = None) -> str:
        return create_permission_str(model, self.get_permission_action_name(action))

    def get_public_access_rules(self, model: type[Model], action: str | None = None):
        config = self._get_bloomerp_config(model)
        if config is None:
            return []
        return config.get_public_access_rules(self.get_public_action_name(action))

    def get_user_access_rules(self, model: type[Model], action: str | None = None):
        config = self._get_bloomerp_config(model)
        if config is None:
            return []
        return config.get_user_access_rules(self.get_permission_action_name(action))

    def has_internal_access(self, model: type[Model], action: str | None = None) -> bool:
        if getattr(self.permission_manager.user, "is_superuser", False):
            return True
        if self.permission_manager.is_anonymous:
            return False
        permission_str = self.get_permission_str(model, action)
        return self.permission_manager.has_global_permission(
            model, permission_str
        ) or self.permission_manager.has_row_level_access(model, permission_str)

    def should_use_public_access(self, model: type[Model], action: str | None = None) -> bool:
        if not self.get_public_access_rules(model, action):
            return False

        config = self._get_bloomerp_config(model)
        if config is not None and not getattr(
            getattr(config, "api_settings", None),
            "public_access_for_authenticated_fallback",
            True,
        ):
            return bool(
                getattr(self.request, "user", None)
                and self.request.user.is_anonymous
            )

        return not self.has_internal_access(model, action)

    def should_use_user_access(self, model: type[Model], action: str | None = None) -> bool:
        if self.permission_manager.is_anonymous:
            return False
        if not self.get_user_access_rules(model, action):
            return False
        return not self.has_internal_access(model, action)

    def _build_public_rule_q(self, model: type[Model], rule) -> Q | None:
        rule_q = Q()
        for filter_rule in rule.filters:
            field_name = str(filter_rule.field or "").strip()
            if not field_name:
                return None

            try:
                model._meta.get_field(field_name)
            except FieldDoesNotExist:
                return None

            operator = str(filter_rule.get_lookup_operator() or "").strip().lower()
            if operator == "ne":
                rule_q &= ~Q(**{field_name: filter_rule.value})
                continue

            filter_key = field_name if operator in {"", "exact"} else f"{field_name}__{operator}"
            rule_q &= Q(**{filter_key: filter_rule.value})

        return rule_q

    def _normalize_user_access_path(self, field_path: str | None) -> str:
        return str(field_path or "").replace(".", "__").strip("_")

    def _is_self_user_access_path(self, field_path: str | None) -> bool:
        return str(field_path or "").strip().lower() == "self"

    def _build_user_rule_q(self, rule) -> Q | None:
        raw_through_field = getattr(rule, "through_field", "")
        through_field = self._normalize_user_access_path(raw_through_field)

        if self._is_self_user_access_path(raw_through_field):
            rule_q = Q(pk=self.request.user.pk)
        else:
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

            filter_key = field_name if operator in {"", "exact"} else f"{field_name}__{operator}"
            rule_q &= Q(**{filter_key: filter_rule.value})

        return rule_q

    def get_queryset(self, model: type[Model], action: str | None = None) -> QuerySet:
        queryset = model.objects.all()

        if self.should_use_user_access(model, action):
            object_ids: set = set()
            for rule in self.get_user_access_rules(model, action):
                rule_q = self._build_user_rule_q(rule)
                if rule_q is None:
                    continue
                object_ids.update(queryset.filter(rule_q).values_list("pk", flat=True))
            if not object_ids:
                return queryset.none()
            return queryset.filter(pk__in=object_ids)

        if self.should_use_public_access(model, action):
            object_ids: set = set()
            unrestricted = False
            for rule in self.get_public_access_rules(model, action):
                rule_q = self._build_public_rule_q(model, rule)
                if rule.filters and rule_q is None:
                    continue
                if not rule.filters:
                    unrestricted = True
                    break
                object_ids.update(queryset.filter(rule_q).values_list("pk", flat=True))
            if unrestricted:
                return queryset
            if not object_ids:
                return queryset.none()
            return queryset.filter(pk__in=object_ids)

        if getattr(self.permission_manager.user, "is_superuser", False):
            return queryset

        permission_str = self.get_permission_str(model, action)
        return self.permission_manager.get_queryset(model, permission_str)

    def _get_public_accessible_field_names(
        self, model: type[Model], action: str | None = None
    ) -> set[str] | None:
        rules = self.get_public_access_rules(model, action)
        if not rules:
            return None

        public_action = self.get_public_action_name(action)
        allowed_fields: set[str] = set()
        for rule in rules:
            rule_fields = rule.get_accessible_fields(public_action)
            if rule_fields is None:
                return None
            allowed_fields.update(rule_fields)
        return allowed_fields

    def _get_user_accessible_field_names(
        self, model: type[Model], action: str | None = None
    ) -> set[str] | None:
        rules = self.get_user_access_rules(model, action)
        if not rules:
            return set()

        permission_action = self.get_permission_action_name(action)
        allowed_fields: set[str] = set()

        for rule in rules:
            field_actions = getattr(rule, "field_actions", {}) or {}
            if not isinstance(field_actions, dict):
                continue

            wildcard_actions = field_actions.get("__all__")
            if wildcard_actions == "__all__" or (
                isinstance(wildcard_actions, list)
                and permission_action in wildcard_actions
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

    def get_accessible_field_names(
        self, model: type[Model], action: str | None = None
    ) -> set[str] | None:
        if self.should_use_user_access(model, action):
            return self._get_user_accessible_field_names(model, action)

        if self.should_use_public_access(model, action):
            return self._get_public_accessible_field_names(model, action)

        if getattr(self.permission_manager.user, "is_superuser", False):
            return None

        permission_str = self.get_permission_str(model, action)
        content_type = ContentType.objects.get_for_model(model)
        accessible_fields = self.permission_manager.get_accessible_fields(
            content_type, permission_str
        )
        return set(accessible_fields.values_list("field", flat=True))

    def has_read_contract(self, model: type[Model], action: str | None = None) -> bool:
        if getattr(self.permission_manager.user, "is_superuser", False):
            return True
        if self.has_internal_access(model, action):
            return True
        if self.should_use_user_access(model, action):
            return True
        if self.should_use_public_access(model, action):
            return True
        return False


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

def generate_serializer(model:Model):
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
        'filterset_class': dynamic_filterset_factory(model)
    })
    
    return Class
