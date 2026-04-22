from bloomerp.forms.document_templates import FreeVariableForm
from bloomerp.models.document_templates import DocumentTemplate
from bloomerp.models.files import File
from bloomerp.router import router
from bloomerp.utils.document_templates import DocumentController
from bloomerp.views.core import BloomerpBaseDetailView
from bloomerp.views.document_templates import EXCLUDE_MODELS


from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import redirect


@router.register(
    path="document-templates/<int:template_id>/",
    name="Document Template generate for {model}",
    route_type="detail",
    url_name="document_template_generate",
    description="Document Template for {model}",
    exclude_models=EXCLUDE_MODELS
    )
class BloomerpDetailDocumentTemplateGenerateView(BloomerpBaseDetailView):
    template_name = "document_template_views/bloomerp_detail_document_generator_view.html"
    model = None

    def post(self, request, *args, **kwargs):
        # Retrieve the instance based on the provided ID
        template_id = self.kwargs["template_id"]
        # Use the retrieved ID as desired
        template = DocumentTemplate.objects.get(pk=template_id)

        try:
            if "instance_select" in request.POST:
                id = request.POST.get("instance_select")
                instance = template.model_variable.get_object_for_this_type(pk=id)
            else:
                instance = self.get_object()

            free_variable_form = FreeVariableForm(template, request.POST)

            if free_variable_form.is_valid():
                data = free_variable_form.cleaned_data
                controller = DocumentController(
                    document_template=template,
                    user=self.request.user
                )
                controller.create_document(template, instance, data)

            # Redirect to a success page or any other desired view
        except Exception as e:
            # Handle the exception
            messages.error(request, f"Document error: {e}")
            # You might want to log the error or provide appropriate feedback to the user

        return redirect(request.path)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        instance = self.get_object()

        # Retrieve document, important that the kwarg = id
        template_id = self.kwargs["template_id"]
        template = DocumentTemplate.objects.get(pk=template_id)

        context["document_template"] = template
        context["free_variable_form"] = FreeVariableForm(document_template=template)

        # Retrieve file
        file_queryset = File.objects.filter(
            meta__document_template=template_id,
            object_id=instance.pk,
            content_type_id=ContentType.objects.get_for_model(self.model),
        ).order_by("-datetime_created")

        context["file_list"] = file_queryset

        return context