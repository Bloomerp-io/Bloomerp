from django.contrib.contenttypes.models import ContentType
from django_countries.fields import Country, CountryField

from bloomerp.field_types import FieldType
from bloomerp.forms.model_form import bloomerp_modelform_factory
from bloomerp.models.application_field import ApplicationField
from bloomerp.tests.base import BaseBloomerpModelTestCase
from bloomerp.tests.utils.dynamic_models import create_test_models


class TestCountryField(BaseBloomerpModelTestCase):
    auto_create_customers = False
    auto_create_users = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.CountryRecordModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "CountryRecord": {
                    "country": CountryField(blank=True),
                    "__str__": lambda self: str(self.country or ""),
                }
            },
            use_bloomerp_base=True,
        )["CountryRecord"]

    def test_application_field_uses_country_field_type_and_choices(self):
        """
        Use case: A model declares a django-countries CountryField.
        Expected result: Its application field preserves the country field type and choice form field.
        """
        # 1. Resolve the generated application field metadata.
        application_field = ApplicationField.objects.get(
            content_type=ContentType.objects.get_for_model(self.CountryRecordModel),
            field="country",
        )

        # 2. Build the form field through the application-field lifecycle.
        form_field = application_field.get_form_field()

        self.assertEqual(application_field.field_type, FieldType.COUNTRY_FIELD.id)
        self.assertEqual(application_field.get_field_type_enum(), FieldType.COUNTRY_FIELD)
        self.assertEqual(form_field.clean("NL"), "NL")
        self.assertGreater(sum(1 for _ in form_field.choices), 200)

    def test_country_field_saves_through_bloomerp_model_form(self):
        """
        Use case: A country code is submitted through a generated Bloomerp model form.
        Expected result: The form validates and persists the selected country.
        """
        # 1. Build and bind the generated form.
        form_class = bloomerp_modelform_factory(
            self.CountryRecordModel,
            fields=["country"],
        )
        form = form_class(data={"country": "BE"})

        # 2. Save and reload the record.
        self.assertTrue(form.is_valid(), form.errors)
        record = form.save()
        record.refresh_from_db()

        self.assertIsInstance(record.country, Country)
        self.assertEqual(record.country.code, "BE")

    def test_country_equals_lookup_renders_country_selector(self):
        """
        Use case: A user chooses an equality filter for a country field.
        Expected result: The filter value input lists countries instead of accepting arbitrary text.
        """
        # 1. Resolve the country application field and equality lookup.
        application_field = ApplicationField.objects.get(
            content_type=ContentType.objects.get_for_model(self.CountryRecordModel),
            field="country",
        )
        lookup = FieldType.COUNTRY_FIELD.get_lookup_by_id("equals")

        # 2. Render the lookup value input.
        html = lookup.value.render(application_field)

        self.assertIn("<select", html)
        self.assertIn('value="NL"', html)
        self.assertIn("Netherlands", html)
