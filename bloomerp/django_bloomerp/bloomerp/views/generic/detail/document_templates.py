from bloomerp.models.document_templates.document_template import DocumentTemplate
from bloomerp.router import router
from bloomerp.views.generic.detail.base import BaseBloomerpDetailView
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

@router.register(
    path="document-templates",
    models="__all__",
    route_type="detail",
    name="Document templates",
    description="Different document templates",
    url_name="document_templates",
)
class DocumentTemplateListDetailView(BaseBloomerpDetailView):
    template_name = "views/generic/detail/document_templates.html"
    
    def get_context_data(self, **kwargs):
        self.object = self.get_object()
        content_type_id = ContentType.objects.get_for_model(
            self.model
        ).id
        ctx = super().get_context_data(**kwargs)
        ctx["content_type_id"] = ContentType.objects.get_for_model(
            model=DocumentTemplate
        ).id
        ctx["model_content_type_id"] = content_type_id
        ctx["data_view_filters"] = {
            "content_types": ctx["model_content_type_id"],
        }
        url = reverse("components_generate_document_template", kwargs={"id": "INSERT_ID"}) + f"?content_type_id={content_type_id}&object_id={self.get_object().id}"
        
        ctx["data_view_args"] = {
            "generate_template_url": url,
            "hide_filters" : "content_types"
        }
        return ctx
    
    

