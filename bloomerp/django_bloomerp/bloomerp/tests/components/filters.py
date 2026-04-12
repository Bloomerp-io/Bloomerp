from bloomerp.tests.base import BaseBloomerpModelTestCase
from django.urls import reverse

from bloomerp.models import ApplicationField
from bloomerp.tests.utils.dynamic_models import create_test_models
from django.db import models

# TODO: Review tests thoroughly

class TestFilterComponent(BaseBloomerpModelTestCase):
    create_foreign_models = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.EventModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "FilterEvent": {
                    "starts_at": models.DateTimeField(),
                }
            },
            use_bloomerp_base=True,
        )["FilterEvent"]

    def test_value_input_renders_full_width_text_input_for_plain_char_field(self):
        application_field = ApplicationField.get_by_field(self.CustomerModel, "first_name")
        url = reverse(
            "components_filters_value_input",
            kwargs={
                "content_type_id": application_field.content_type_id,
                "application_field_id": application_field.id,
            },
        )

        response = self.client.get(url, {"lookup_value": "equals"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<input', html=False)
        self.assertContains(response, 'class="input w-full"', html=False)

    def test_value_input_renders_select_for_choice_backed_application_field(self):
        application_field = ApplicationField.get_by_field(self.CustomerModel, "first_name")
        application_field.meta = {
            "choices": [
                ["full_time", "Full Time"],
                ["part_time", "Part Time"],
            ]
        }
        application_field.save(update_fields=["meta"])

        url = reverse(
            "components_filters_value_input",
            kwargs={
                "content_type_id": application_field.content_type_id,
                "application_field_id": application_field.id,
            },
        )

        response = self.client.get(url, {"lookup_value": "equals"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<select', html=False)
        self.assertContains(response, 'class="select w-full"', html=False)
        self.assertContains(response, 'Full Time', html=False)

    def test_value_input_renders_boolean_select_for_is_null_lookup(self):
        application_field = ApplicationField.get_by_field(self.CustomerModel, "first_name")
        url = reverse(
            "components_filters_value_input",
            kwargs={
                "content_type_id": application_field.content_type_id,
                "application_field_id": application_field.id,
            },
        )

        response = self.client.get(url, {"lookup_value": "is_null"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<select', html=False)
        self.assertContains(response, 'class="select w-full"', html=False)
        self.assertContains(response, '<option value="true">True</option>', html=False)
        self.assertContains(response, '<option value="false">False</option>', html=False)

    def test_value_input_renders_datetime_local_input_for_datetime_field(self):
        application_field = ApplicationField.get_by_field(self.EventModel, "starts_at")
        url = reverse(
            "components_filters_value_input",
            kwargs={
                "content_type_id": application_field.content_type_id,
                "application_field_id": application_field.id,
            },
        )

        response = self.client.get(url, {"lookup_value": "equals"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<input', html=False)
        self.assertContains(response, 'type="datetime-local"', html=False)
        self.assertContains(response, 'class="input w-full"', html=False)

    def test_lookup_operators_include_is_null_for_foreign_key_fields(self):
        application_field = ApplicationField.get_by_field(self.CustomerModel, "country")
        url = reverse(
            "components_filters_lookup_operators",
            kwargs={
                "content_type_id": application_field.content_type_id,
                "application_field_id": application_field.id,
            },
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="is_null"', html=False)
