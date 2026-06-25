from django.urls import reverse

from bloomerp.models.document_templates.document_template import DocumentTemplate
from bloomerp.router import router
from bloomerp.views.generic.detail.base import BaseBloomerpDetailView
from django.views.generic import TemplateView

@router.register(
    path="generate",
    route_type="detail",
    models=DocumentTemplate,
    name="Generate PDF",
    description="Generate pdf from document template"
)
class DocumentTemplateGenerateView(BaseBloomerpDetailView):
    template_name = "utils/load_component_view.html"
    model = DocumentTemplate
    
    def get_context_data(self, **kwargs):
        ctx =  super().get_context_data(**kwargs)
        ctx["url"] = reverse("components_generate_document_template", kwargs={
            "id" : self.get_object().id
        })
        return ctx