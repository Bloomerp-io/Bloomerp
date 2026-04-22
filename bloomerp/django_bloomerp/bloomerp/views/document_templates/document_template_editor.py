from bloomerp.models.document_templates import DocumentTemplate
from bloomerp.router import router
from bloomerp.views.core import BaseBloomerpDetailView


from django.views.generic.edit import UpdateView


@router.register(
    models = DocumentTemplate,
    path="editor",
    route_type="detail",
    name="Editor",
    url_name="editor",
    description="Document Template Editor"
    )
class BloomerpDocumentTemplateEditorView(BaseBloomerpDetailView, UpdateView):
    model = DocumentTemplate
    template_name = "document_template_views/bloomerp_document_template_editor_view.html"
    fields = ["template"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["args"] = f"template_id={self.object.id}"
        return context