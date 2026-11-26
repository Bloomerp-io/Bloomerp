from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from bloomerp.models.document_templates.document_template import DocumentTemplate
from bloomerp.router import router
from bloomerp.tokens import DataviewToken
from bloomerp.views.generic.detail.base import BaseBloomerpDetailView
from bloomerp.views.mixins.dataview_mixin import DataviewMixin


@router.register(
    path="document-templates",
    models="__all__",
    route_type="detail",
    name="Document templates",
    description="Different document templates",
    url_name="document_templates",
)
class DocumentTemplateListDetailView(DataviewMixin, BaseBloomerpDetailView):
    """List document templates applicable to the current record."""

    template_name = "views/generic/detail/document_templates.html"

    def get_dataview_content_type_id(self) -> int:
        """Use DocumentTemplate as the model rendered by the shared loader."""
        return ContentType.objects.get_for_model(DocumentTemplate).pk

    def get_dataview_token(self) -> DataviewToken:
        """Pin the template table and generation context to the current record."""
        content_type_id = str(ContentType.objects.get_for_model(self.model).pk)
        layout = next(
            view for view in DocumentTemplate.bloomerp_config.model_view_settings.default_dataviews
            if view.is_default
        )
        return DataviewToken(
            model=DocumentTemplate,
            user=self.request.user,
            expiry=timezone.now() + timedelta(hours=1),
            dataview=layout.model_copy(update={
                "default_filters": {"content_types": content_type_id},
                "component_args": {
                    "document_content_type_id": content_type_id,
                    "document_object_id": str(self.object.pk),
                },
                "item_click_action_id": "generate-document",
            }),
            dataview_actions=["filter"],
        )

