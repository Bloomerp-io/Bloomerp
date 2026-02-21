from typing import Any
from django.apps import apps
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.db.models.fields.reverse_related import ManyToOneRel
from bloomerp.models.communication import Comment
from bloomerp.models.files import File
from bloomerp.router import router
from bloomerp.views.core.base_detail import BloomerpBaseDetailView
from django.contrib.contenttypes.models import ContentType

class ForeignRelationshipView(PermissionRequiredMixin, BloomerpBaseDetailView):
    template_name: str = "detail_views/bloomerp_foreign_relationship_view.html"
    model = None
    related_model = None 
    attribute_name = None

    def get_permission_required(self):
        return [
            f"{self.model._meta.app_label}.view_{self.model._meta.model_name}",
            f"{self.related_model._meta.app_label}.view_{self.related_model._meta.model_name}",
        ]

    def get_context_data(self, **kwargs: Any) -> dict:
        context = super().get_context_data(**kwargs)
        related_accessor = getattr(self.object, self.attribute_name, None)
        context["foreign_content_type_id"] = ContentType.objects.get_for_model(self.related_model).id
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
                }
            )

    return relationship_specs


for spec in _iter_foreign_relationship_specs():
    model = spec["model"]
    related_model = spec["related_model"]
    attribute_name = spec["attribute_name"]

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
    
    




