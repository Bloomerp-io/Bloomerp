from typing import Any

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db.models.fields.reverse_related import ManyToOneRel

from bloomerp.filters.definition import Filter, FilterCondition, Filters
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.communication import Comment
from bloomerp.models.files import FileNode
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.tokens import DataviewToken, get_token
from bloomerp.views.generic.detail.base import BaseBloomerpDetailView
from bloomerp.views.mixins.dataview_mixin import DataviewMixin


class ForeignRelationshipView(DataviewMixin, BaseBloomerpDetailView):
    dataview_filter_shorthand = True
    model = None
    related_model = None 
    attribute_name = None
    relationship_field_name = None
    permission_field_name = None


    def get_relationship_field(self) -> ApplicationField | None:
        field_name = self.permission_field_name or self.attribute_name
        return ApplicationField.get_by_field(self.model, field_name)

    def has_permission(self) -> bool:
        permission_manager = UserPolicyManager(self.request.user)
        relationship_field = self.get_relationship_field()

        if relationship_field is None:
            return False

        return (
            permission_manager.has_access_to_object(self.get_object(), BloomerpPermission.VIEW)
            and permission_manager.has_field_permission(relationship_field, BloomerpPermission.VIEW)
        )

    def get_dataview_content_type_id(self) -> int:
        """Render the model on the reverse side of the relationship."""
        return ContentType.objects.get_for_model(self.related_model).pk

    def get_dataview_filters(self) -> Filters:
        """Scope the dataview to records related to the current object."""
        if self.relationship_dataview_token() is not None:
            return []
        return [Filter(connector="AND", conditions=[FilterCondition(
            field_path=self.relationship_field_name, lookup_id="equals", value=str(self.object.pk),
        )])]

    def get_dataview_args(self) -> dict[str, str]:
        """Pass the relationship field to the frontend's filter controls."""
        args = {"hide_filters": self.relationship_field_name}
        if self.relationship_dataview_token() is not None:
            args["related_record"] = str(self.object.pk)
        return args

    def relationship_dataview_token(self) -> DataviewToken | None:
        """Use the context's related layout when it targets this relationship."""
        context = get_token(self.request)
        token = context.dataviews.get(self.related_model) if context else None
        return token if token and token.relationship_field == self.relationship_field_name else None


def _iter_foreign_relationship_specs() -> list[dict[str, Any]]:
    """Discover ordinary reverse relationships, excluding dedicated file-node and comment views."""
    relationship_specs: list[dict[str, Any]] = []
    skip_models = {FileNode, Comment}

    for model in apps.get_models():
        if model in skip_models:
            continue

        for field in model._meta.get_fields():
            if not isinstance(field, ManyToOneRel):
                continue

            if field.related_model in skip_models:
                continue

            attribute_name = field.get_accessor_name()
            if not attribute_name or attribute_name in {"created_by", "updated_by"}:
                continue

            relationship_specs.append(
                {
                    "model": model,
                    "related_model": field.related_model,
                    "attribute_name": attribute_name,
                    "relationship_field_name": field.field.name,
                    "permission_field_name": field.name,
                }
            )

    return relationship_specs


for spec in _iter_foreign_relationship_specs():
    model = spec["model"]
    related_model = spec["related_model"]
    attribute_name = spec["attribute_name"]
    relationship_field_name = spec["relationship_field_name"]
    permission_field_name = spec["permission_field_name"]

    dynamic_view_name = (
        f"{model.__name__}{related_model.__name__}{attribute_name.title().replace('_', '')}ForeignRelationshipView"
    )

    DynamicForeignRelationshipView = type(
        dynamic_view_name,
        (ForeignRelationshipView,),
        {
            "model": model,
            "related_model": related_model,
            "attribute_name": attribute_name,
            "relationship_field_name": relationship_field_name,
            "permission_field_name": permission_field_name,
        },
    )

    router.register(
        path=attribute_name,
        name="{related_model_plural}",
        url_name=f"{attribute_name}_relationship",
        description="{related_model_plural} relationship for {model}",
        route_type="detail",
        models=[model],
        message_format_values={
            "related_model_plural": related_model._meta.verbose_name_plural,
        },
    )(DynamicForeignRelationshipView)
    
    



