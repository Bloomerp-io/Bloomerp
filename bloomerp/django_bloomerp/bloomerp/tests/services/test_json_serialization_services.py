from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from django.contrib.contenttypes.models import ContentType

from bloomerp.models.forms.form import Form
from bloomerp.models.forms.form_submission import FormSubmission
from bloomerp.services.form_services import FormManager
from bloomerp.tests.base import BaseBloomerpModelTestCase
from bloomerp.utils.json_serialization import make_json_safe


class JsonSerializationServicesTestCase(BaseBloomerpModelTestCase):
    create_foreign_models = True

    def test_make_json_safe_serializes_django_values_recursively(self):
        country = self.CountryModel.objects.first()
        countries = self.CountryModel.objects.order_by("pk")[:2]
        identifier = uuid4()

        serialized = make_json_safe(
            {
                "country": country,
                "countries": countries,
                "nested": {
                    "date": date(2026, 6, 1),
                    "datetime": datetime(2026, 6, 1, 12, 30),
                    "decimal": Decimal("12.50"),
                    "uuid": identifier,
                },
            }
        )

        self.assertEqual(serialized["country"], country.pk)
        self.assertEqual(serialized["countries"], [item.pk for item in countries])
        self.assertEqual(serialized["nested"]["date"], "2026-06-01")
        self.assertEqual(serialized["nested"]["datetime"], "2026-06-01T12:30:00")
        self.assertEqual(serialized["nested"]["decimal"], "12.50")
        self.assertEqual(serialized["nested"]["uuid"], str(identifier))

    def test_form_manager_register_submission_serializes_cleaned_data(self):
        country = self.CountryModel.objects.first()
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        form = Form.objects.create(
            name="Customer form",
            content_type=content_type,
        )

        response = FormManager(form).register_submission(
            {
                "first_name": "Lisa",
                "country": country,
            },
            request=None,
        )

        self.assertTrue(response.submitted)
        submission = FormSubmission.objects.get(pk=response.form_submission.pk)
        self.assertEqual(submission.data["first_name"], "Lisa")
        self.assertEqual(submission.data["country"], country.pk)
