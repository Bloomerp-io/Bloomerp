from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.db import models

from bloomerp.tests.base import BaseBloomerpModelTestCase
from bloomerp.tests.utils.dynamic_models import create_test_models


class TestDeleteView(BaseBloomerpModelTestCase):
    auto_create_customers = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.NoteModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "DeleteNote": {
                    "customer": models.ForeignKey(cls.CustomerModel, on_delete=models.CASCADE),
                    "name": models.CharField(max_length=100),
                }
            },
            use_bloomerp_base=True,
        )["DeleteNote"]

    def extendedSetup(self):
        self.customer = self.CustomerModel.objects.create(
            first_name="Alice",
            last_name="Example",
            age=31,
        )
        self.note = self.NoteModel.objects.create(
            customer=self.customer,
            name="Cascade note",
        )
        self.content_type = ContentType.objects.get_for_model(self.CustomerModel)
        self.url = reverse(
            "customers_detail_delete",
            kwargs={"pk": self.customer.pk},
        )
        self.component_url = reverse(
            "components_delete_object",
            kwargs={
                "content_type_id": self.content_type.pk,
                "object_id": self.customer.pk,
            },
        )

    def test_get_requires_delete_permission(self):
        """
        Checks whether the 
        """
        self.client.force_login(self.normal_user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_get_shows_related_objects_that_would_be_deleted(self):
        self.client.force_login(self.admin_user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Related objects that would be deleted")
        self.assertContains(response, str(self.note))
        self.assertContains(response, "Delete")

    def test_component_get_shows_related_objects_that_would_be_deleted(self):
        self.client.force_login(self.admin_user)

        response = self.client.get(self.component_url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Related objects that would be deleted")
        self.assertContains(response, str(self.note))

    def test_post_deletes_object_and_related_objects(self):
        self.client.force_login(self.admin_user)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("customers_model"))
        self.assertFalse(self.CustomerModel.objects.filter(pk=self.customer.pk).exists())
        self.assertFalse(self.NoteModel.objects.filter(pk=self.note.pk).exists())

    def test_post_htmx_redirects_to_list_view_after_delete(self):
        self.client.force_login(self.admin_user)

        response = self.client.post(self.url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"], reverse("customers_model"))
        self.assertFalse(self.CustomerModel.objects.filter(pk=self.customer.pk).exists())

    def test_component_post_refreshes_from_list_context(self):
        self.client.force_login(self.admin_user)

        response = self.client.post(
            self.component_url,
            HTTP_HX_REQUEST="true",
            HTTP_HX_CURRENT_URL=reverse("customers_model"),
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Refresh"], "true")
        self.assertFalse(self.CustomerModel.objects.filter(pk=self.customer.pk).exists())

    def test_component_post_redirects_from_detail_context(self):
        self.client.force_login(self.admin_user)

        response = self.client.post(
            self.component_url,
            HTTP_HX_REQUEST="true",
            HTTP_HX_CURRENT_URL=self.customer.get_absolute_url(),
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"], reverse("customers_model"))
        self.assertFalse(self.CustomerModel.objects.filter(pk=self.customer.pk).exists())
