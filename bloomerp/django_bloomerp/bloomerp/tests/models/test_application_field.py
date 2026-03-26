from django.contrib.contenttypes.models import ContentType

from bloomerp.models.access_control.field_policy import FieldPolicy
from bloomerp.models.access_control.policy import Policy
from bloomerp.models.application_field import ApplicationField
from bloomerp.tests.base import BaseBloomerpModelTestCase


class TestApplicationField(BaseBloomerpModelTestCase):
    auto_create_customers = False

    def test_pk_application_field_returns_widget(self):
        content_type = ContentType.objects.get_for_model(Policy)
        application_field = ApplicationField.objects.get(
            content_type=content_type,
            field="pk",
        )

        widget = application_field.get_widget()

        self.assertIsNotNone(widget)

    def test_pk_application_field_returns_form_field(self):
        content_type = ContentType.objects.get_for_model(Policy)
        application_field = ApplicationField.objects.get(
            content_type=content_type,
            field="pk",
        )

        form_field = application_field.get_form_field()

        self.assertIsNone(form_field)

    def test_reverse_relation_application_field_returns_widget(self):
        content_type = ContentType.objects.get_for_model(FieldPolicy)
        application_field = ApplicationField.objects.get(
            content_type=content_type,
            field="policies",
        )

        widget = application_field.get_widget()

        self.assertIsNotNone(widget)

    def test_reverse_relation_application_field_returns_no_form_field(self):
        content_type = ContentType.objects.get_for_model(FieldPolicy)
        application_field = ApplicationField.objects.get(
            content_type=content_type,
            field="policies",
        )

        form_field = application_field.get_form_field()

        self.assertIsNone(form_field)