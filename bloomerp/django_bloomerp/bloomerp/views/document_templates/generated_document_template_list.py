from bloomerp.models.document_templates import DocumentTemplate
from bloomerp.models.files import File
from bloomerp.router import router
from bloomerp.views.core import BaseBloomerpDetailView


@router.register(
    models = DocumentTemplate,
    path="generated-documents",
    route_type="detail",
    name="Generated documents",
    url_name="generated_documents",
    description="List of generated documents for the document template"
    )
class BloomerpDocumentTemplateGeneratedDocumentsView(BaseBloomerpDetailView):
    model = DocumentTemplate
    template_name = "document_template_views/bloomerp_document_template_generated_documents_view.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Get all files associated with the document template
        files = File.objects.filter(meta__document_template=self.get_object().pk)
        context['files'] = files

        return context