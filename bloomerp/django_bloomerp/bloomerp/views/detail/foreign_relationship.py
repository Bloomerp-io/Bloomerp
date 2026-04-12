from typing import Any
from django.apps import apps
from django.db.models.fields.reverse_related import ManyToOneRel
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.communication import Comment
from bloomerp.models.files import File
from bloomerp.router import router
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.views.detail.base_detail import BloomerpBaseDetailView
from django.contrib.contenttypes.models import ContentType

class ForeignRelationshipView(BloomerpBaseDetailView):
    template_name: str = "detail_views/bloomerp_foreign_relationship_view.html"
    model = None
    related_model = None 
    attribute_name = None
    relationship_field_name = None
    permission_field_name = None


    def get_relationship_field(self) -> ApplicationField | None:
        field_name = self.permission_field_name or self.attribute_name
        return ApplicationField.get_by_field(self.model, field_name)

    def has_permission(self) -> bool:
        permission_manager = UserPermissionManager(self.request.user)
        permission_str = create_permission_str(self.model, "view")
        relationship_field = self.get_relationship_field()

        if relationship_field is None:
            return False

        return (
            permission_manager.has_access_to_object(self.get_object(), permission_str)
            and permission_manager.has_field_permission(relationship_field, permission_str)
        )

    def get_context_data(self, **kwargs: Any) -> dict:
        context = super().get_context_data(**kwargs)
        context["foreign_content_type_id"] = ContentType.objects.get_for_model(self.related_model).id
        query_params = self.request.GET.copy()
        if self.relationship_field_name:
            query_params[self.relationship_field_name] = str(self.object.pk)
        context["foreign_relationship_querystring"] = query_params.urlencode()
        return context


def _iter_foreign_relationship_specs() -> list[dict[str, Any]]:
    relationship_specs: list[dict[str, Any]] = []
    skip_models = {File, Comment}

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
        name=related_model._meta.verbose_name_plural.title(),
        url_name=f"{attribute_name}_relationship",
        description=f"{related_model._meta.verbose_name_plural.title()} relationship for {{model}}",
        route_type="detail",
        models=[model],
    )(DynamicForeignRelationshipView)
    
    




