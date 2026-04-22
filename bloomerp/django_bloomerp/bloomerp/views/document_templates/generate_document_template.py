from bloomerp.forms.document_templates import GenerateDocumentForm
from bloomerp.models.document_templates import DocumentTemplate
from bloomerp.router import router
from bloomerp.views.core import BaseBloomerpDetailView


@router.register(
    models = DocumentTemplate,
    path="generate-document",
    route_type="detail",
    name="Generate document",
    url_name="generate_document",
    description="Generate document for the document template"
    )
class BloomerpDocumentTemplateGenerateView(BaseBloomerpDetailView):
    model = DocumentTemplate
    template_name = "document_template_views/bloomerp_document_template_generate_view.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Check if document template has 

        context['form'] = GenerateDocumentForm(self.object)

        return context