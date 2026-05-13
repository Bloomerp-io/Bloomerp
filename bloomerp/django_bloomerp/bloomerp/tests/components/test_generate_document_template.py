import base64
from unittest.mock import Mock, patch

from django import forms
from django.test import RequestFactory, SimpleTestCase

from bloomerp.components.document_templates.generate_document_template import generate_document_template
from bloomerp.models.document_templates import DocumentTemplate


class _AuthenticatedUser:
    is_authenticated = True


class _ValidForm(forms.Form):
    name = forms.CharField(required=False)
    persist = forms.BooleanField(required=False)


class GenerateDocumentTemplateComponentTests(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()
        self.user = _AuthenticatedUser()

    def _document_template(self):
        document_template = Mock()
        document_template.content_types.all.return_value = []
        return document_template

    def _content_type(self):
        content_type = Mock()
        content_type.model_class.return_value = DocumentTemplate
        return content_type

    @patch("bloomerp.components.document_templates.generate_document_template.ContentType")
    @patch("bloomerp.components.document_templates.generate_document_template.UserPermissionManager")
    @patch("bloomerp.components.document_templates.generate_document_template.DocumentTemplateService")
    @patch("bloomerp.components.document_templates.generate_document_template.get_object_or_404")
    def test_post_embeds_generated_pdf_as_base64_data_url(
        self,
        get_object_or_404,
        service_cls,
        permission_manager_cls,
        content_type_cls,
    ) -> None:
        pdf_bytes = b"%PDF-1.4 hello world"
        expected_base64 = base64.b64encode(pdf_bytes).decode("ascii")

        get_object_or_404.return_value = self._document_template()
        content_type_cls.objects.get_for_model.return_value = self._content_type()
        permission_manager_cls.return_value.has_global_permission.return_value = True
        service = service_cls.return_value
        service.get_form.return_value = _ValidForm
        service.generate.return_value = pdf_bytes
        service.get_files.return_value.order_by.return_value = []

        request = self.factory.post("/components/document_templates/test-id/", data={"name": "value"})
        request.user = self.user

        response = generate_document_template(request, "test-id")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"data:application/pdf;base64,{expected_base64}", html=False)

    @patch("bloomerp.components.document_templates.generate_document_template.ContentType")
    @patch("bloomerp.components.document_templates.generate_document_template.UserPermissionManager")
    @patch("bloomerp.components.document_templates.generate_document_template.DocumentTemplateService")
    @patch("bloomerp.components.document_templates.generate_document_template.get_object_or_404")
    def test_post_persists_generated_pdf_when_requested(
        self,
        get_object_or_404,
        service_cls,
        permission_manager_cls,
        content_type_cls,
    ) -> None:
        pdf_bytes = b"%PDF-1.4 persisted"

        get_object_or_404.return_value = self._document_template()
        content_type_cls.objects.get_for_model.return_value = self._content_type()
        permission_manager_cls.return_value.has_global_permission.return_value = True
        service = service_cls.return_value
        service.get_form.return_value = _ValidForm
        service.generate.return_value = pdf_bytes
        service.get_files.return_value.order_by.return_value = []

        request = self.factory.post(
            "/components/document_templates/test-id/",
            data={"name": "value", "persist": "on"},
        )
        request.user = self.user

        response = generate_document_template(request, "test-id")

        self.assertEqual(response.status_code, 200)
        service.create_file.assert_called_once_with(pdf_bytes, instance=None)
