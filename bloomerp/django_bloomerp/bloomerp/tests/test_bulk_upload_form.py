from django.contrib.contenttypes.models import ContentType

from bloomerp.forms.bulk_upload_form import BloomerpBulkForm
from bloomerp.models import ApplicationField
from bloomerp.tests.base import BaseBloomerpModelTestCase


class TestBloomerpBulkForm(BaseBloomerpModelTestCase):
    def test_default_behavior_skips_ineligible_fields(self):
        """
        Default behavior being for imports
        TODO: This will probably change as soon as want to allow for bulk updates via files
        """
        form = BloomerpBulkForm(
            content_type=ContentType.objects.get_for_model(self.CustomerModel),
            application_fields=ApplicationField.get_for_model(self.CustomerModel).order_by("field"),
        )

        self.assertNotIn("pk", form.fields)

    def test_skip_ineligible_fields_false_includes_non_editable_fields(self):
        form = BloomerpBulkForm(
            content_type=ContentType.objects.get_for_model(self.CustomerModel),
            application_fields=ApplicationField.get_for_model(self.CustomerModel).order_by("field"),
            skip_ineligible_fields=False,
        )

        self.assertIn("pk", form.fields)

    def test_import_mode_marks_required_fields_as_selected_and_disabled(self):
        """
        Test to check whether import mode marks required fields as selected and disabled
        """
        form = BloomerpBulkForm(
            content_type=ContentType.objects.get_for_model(self.CustomerModel),
            application_fields=ApplicationField.get_for_model(self.CustomerModel).order_by("field"),
            mode="import",
        )

        self.assertTrue(form.fields["first_name"].disabled)
        self.assertTrue(form.fields["first_name"].initial)
        self.assertEqual(form.submit_label, "Download template")

    def test_export_mode_does_not_force_required_fields(self):
        """
        Test to check whether export mode enforces required fields
        """
        form = BloomerpBulkForm(
            content_type=ContentType.objects.get_for_model(self.CustomerModel),
            application_fields=ApplicationField.get_for_model(self.CustomerModel).order_by("field"),
            skip_ineligible_fields=False,
            mode="export",
        )

        self.assertFalse(form.fields["first_name"].disabled)
        self.assertFalse(form.fields["first_name"].initial)
        self.assertEqual(form.submit_label, "Export")
