from django.contrib.contenttypes.models import ContentType
from unittest.mock import patch

from bloomerp.tests.base import BaseBloomerpModelTestCase

# TODO: Check tests and add descriptions

class TestObjectPreview(BaseBloomerpModelTestCase):
    def test_object_preview_renders_for_authorized_user(self):
        customer = self.CustomerModel.objects.first()
        content_type = ContentType.objects.get_for_model(self.CustomerModel)

        self.client.force_login(self.admin_user)
        response = self.client.get(f"/components/object-preview/{content_type.pk}/{customer.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, str(customer))

    def test_object_preview_shows_message_without_direct_access(self):
        customer = self.CustomerModel.objects.first()
        content_type = ContentType.objects.get_for_model(self.CustomerModel)

        self.client.force_login(self.normal_user)
        response = self.client.get(f"/components/object-preview/{content_type.pk}/{customer.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You do not have permission to preview this object.")

    def test_object_preview_degrades_when_a_field_render_fails(self):
        customer = self.CustomerModel.objects.first()
        content_type = ContentType.objects.get_for_model(self.CustomerModel)

        self.client.force_login(self.admin_user)
        with patch(
            "bloomerp.templatetags.bloomerp.build_detail_value_context",
            side_effect=RuntimeError("broken preview field"),
        ):
            response = self.client.get(f"/components/object-preview/{content_type.pk}/{customer.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Preview is not available for this field.")
