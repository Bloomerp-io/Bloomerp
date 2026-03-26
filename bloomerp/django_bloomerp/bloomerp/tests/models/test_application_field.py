from django.contrib.contenttypes.models import ContentType

from bloomerp.models.access_control.field_policy import FieldPolicy
from bloomerp.models.access_control.policy import Policy
from bloomerp.models.access_control.row_policy import RowPolicy
from bloomerp.models.access_control.row_policy_rule import RowPolicyRule
from bloomerp.models.application_field import ApplicationField
from bloomerp.field_types import Lookup
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

    def test_property_backed_application_field_returns_widget(self):
        content_type = ContentType.objects.get_for_model(RowPolicyRule)
        application_field = ApplicationField.objects.get(
            content_type=content_type,
            field="content_type",
        )

        widget = application_field.get_widget()

        self.assertIsNotNone(widget)

    def test_property_backed_application_field_returns_no_form_field(self):
        content_type = ContentType.objects.get_for_model(RowPolicyRule)
        application_field = ApplicationField.objects.get(
            content_type=content_type,
            field="content_type",
        )

        form_field = application_field.get_form_field()

        self.assertIsNone(form_field)

    def test_row_policy_rule_detail_view_renders_property_backed_field(self):
        target_content_type = ContentType.objects.get_for_model(Policy)
        target_field = ApplicationField.objects.get(
            content_type=target_content_type,
            field="name",
        )
        row_policy = RowPolicy.objects.create(
            content_type=target_content_type,
            name="Policy visibility",
        )
        row_policy_rule = RowPolicyRule.objects.create(
            row_policy=row_policy,
            rule={
                "application_field_id": str(target_field.pk),
                "operator": Lookup.EQUALS.value.id,
                "value": "Policy",
            },
        )

        self.client.force_login(self.admin_user)
        response = self.client.get(f"/misc/access-control-row-policy-rules/{row_policy_rule.pk}/")

        self.assertEqual(response.status_code, 200)