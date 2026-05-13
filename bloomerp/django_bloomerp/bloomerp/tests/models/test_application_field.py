from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models

from bloomerp.models.base_bloomerp_model import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.access_control.field_policy import FieldPolicy
from bloomerp.models.access_control.policy import Policy
from bloomerp.models.access_control.row_policy import RowPolicy
from bloomerp.models.access_control.row_policy_rule import RowPolicyRule
from bloomerp.models.application_field import ApplicationField
from bloomerp.services.one_to_many_field_services import save_submitted_one_to_many_fields
from bloomerp.field_types import FieldType, Lookup
from bloomerp.form_fields.phone_number_field import PhoneNumberFormField
from bloomerp.model_fields.phone_number_field import PhoneNumberField
from bloomerp.tests.base import BaseBloomerpModelTestCase
from bloomerp.tests.utils.dynamic_models import create_test_models
from bloomerp.widgets.code_editor_widget import CodeEditorWidget
from bloomerp.widgets.one_to_many_field_widget import OneToManyFieldWidget
from bloomerp.widgets.phone_number_widget import PhoneNumberWidget


class TestApplicationField(BaseBloomerpModelTestCase):
    auto_create_customers = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.CustomerLineModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "CustomerLine": {
                    "customer": models.ForeignKey(
                        cls.CustomerModel,
                        on_delete=models.CASCADE,
                        related_name="lines",
                    ),
                    "description": models.CharField(max_length=100, blank=True),
                    "hours": models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True),
                    "__str__": lambda self: self.description,
                }
            },
            use_bloomerp_base=True,
        )["CustomerLine"]
        cls.PhoneRecordModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "PhoneRecord": {
                    "phone": PhoneNumberField(blank=True, null=True),
                    "__str__": lambda self: str(self.phone or ""),
                }
            },
            use_bloomerp_base=True,
        )["PhoneRecord"]

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

        self.assertIsInstance(widget, OneToManyFieldWidget)

    def test_one_to_many_field_type_owns_widget_behavior(self):
        field_type = FieldType.ONE_TO_MANY_FIELD.value

        self.assertIs(field_type.widget_cls, OneToManyFieldWidget)
        self.assertEqual(field_type.widget_related_model_attr, "related_model")
        self.assertTrue(field_type.editable_without_form_field)

    def test_one_to_many_widget_renders_inline_table_markup(self):
        content_type = ContentType.objects.get_for_model(FieldPolicy)
        application_field = ApplicationField.objects.get(
            content_type=content_type,
            field="policies",
        )

        html = application_field.get_widget().render(
            name="policies",
            value=None,
            attrs={"disabled": "disabled"},
        )

        self.assertIn("one-to-many-field-widget", html)
        self.assertIn("Add Row", html)
        self.assertIn("disabled", html)
        self.assertNotIn("fa-gear", html)
        self.assertIn("data-one-to-many-add-row", html)
        self.assertIn("policies__ __prefix__ __id".replace(" ", ""), html)

    def test_one_to_many_widget_uses_layout_config_inline_fields(self):
        content_type = ContentType.objects.get_for_model(FieldPolicy)
        application_field = ApplicationField.objects.get(
            content_type=content_type,
            field="policies",
        )

        widget = application_field.get_widget(layout_config={"inline_fields": ["name"]})

        self.assertEqual(widget.fields, ["name"])

    def test_one_to_many_widget_excludes_parent_foreign_key_column(self):
        content_type = ContentType.objects.get_for_model(FieldPolicy)
        application_field = ApplicationField.objects.get(
            content_type=content_type,
            field="policies",
        )

        widget = application_field.get_widget(
            layout_config={"inline_fields": ["name", "field_policy"]}
        )

        self.assertEqual([column.field for column in widget._get_columns()], ["name"])

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

    def test_json_application_field_uses_json_code_editor_widget(self):
        content_type = ContentType.objects.get_for_model(ApplicationField)
        application_field = ApplicationField.objects.get(
            content_type=content_type,
            field="meta",
        )

        widget = application_field.get_widget()

        self.assertIsInstance(widget, CodeEditorWidget)
        self.assertEqual(widget.language, "json")

    def test_phone_number_field_type_uses_phone_field_parts(self):
        field_type = FieldType.PHONE_NUMBER_FIELD.value

        self.assertEqual(field_type.id, "PhoneNumberField")
        self.assertIs(field_type.model_field_cls, PhoneNumberField)
        self.assertIs(field_type.form_field_cls, PhoneNumberFormField)
        self.assertIs(field_type.widget_cls, PhoneNumberWidget)
        self.assertEqual(field_type.default_model_field_args["max_length"], 30)
        self.assertIn(Lookup.CONTAINS, field_type.lookups)

    def test_phone_number_form_field_normalizes_country_codes(self):
        form_field = PhoneNumberFormField()

        self.assertEqual(form_field.clean("+32 470 12 34 56"), "+32470123456")
        self.assertEqual(form_field.clean("0032 470 12 34 56"), "+32470123456")

    def test_phone_number_form_field_rejects_invalid_values(self):
        form_field = PhoneNumberFormField()

        with self.assertRaises(ValidationError):
            form_field.clean("call me maybe")

    def test_phone_number_model_field_formfield_uses_phone_widget(self):
        model_field = PhoneNumberField()
        form_field = model_field.formfield()

        self.assertIsInstance(form_field, PhoneNumberFormField)
        self.assertIsInstance(form_field.widget, PhoneNumberWidget)
        self.assertEqual(form_field.widget.input_type, "tel")

    def test_stale_char_field_metadata_uses_phone_number_widget_for_phone_field(self):
        content_type = ContentType.objects.get_for_model(self.PhoneRecordModel)
        application_field = ApplicationField.objects.get(
            content_type=content_type,
            field="phone",
        )
        application_field.field_type = FieldType.CHAR_FIELD.id

        form_field = application_field.get_form_field()

        self.assertEqual(application_field.get_field_type_enum(), FieldType.PHONE_NUMBER_FIELD)
        self.assertIsInstance(form_field, PhoneNumberFormField)
        self.assertIsInstance(form_field.widget, PhoneNumberWidget)

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

    def test_one_to_many_save_service_updates_and_creates_rows(self):
        customer = self.create_customer("Inline", "Editor", 37)
        existing_line = self.CustomerLineModel.objects.create(
            customer=customer,
            description="Old description",
            hours="1.00",
        )
        parent_content_type = ContentType.objects.get_for_model(self.CustomerModel)
        relation_field = ApplicationField.objects.get(
            content_type=parent_content_type,
            field="lines",
        )
        layout = FieldLayout(
            rows=[
                LayoutRow(
                    title="Inline rows",
                    columns=1,
                    items=[
                        LayoutItem(
                            id=str(relation_field.pk),
                            colspan=1,
                            config={"inline_fields": ["description", "hours"]},
                        )
                    ],
                )
            ]
        )

        save_submitted_one_to_many_fields(
            parent_object=customer,
            layout=layout,
            submitted_data={
                "lines__0__id": str(existing_line.pk),
                "lines__0__description": "Updated description",
                "lines__0__hours": "2.50",
                "lines__1__id": "",
                "lines__1__description": "New line",
                "lines__1__hours": "3.75",
            },
            user=self.admin_user,
        )

        existing_line.refresh_from_db()
        self.assertEqual(existing_line.description, "Updated description")
        self.assertEqual(str(existing_line.hours), "2.50")
        self.assertTrue(
            self.CustomerLineModel.objects.filter(
                customer=customer,
                description="New line",
                hours="3.75",
            ).exists()
        )

    def test_one_to_many_save_service_raises_validation_error_for_missing_required_fields(self):
        row_policy = RowPolicy.objects.create(
            content_type=ContentType.objects.get_for_model(Policy),
            name="Required row policy",
        )
        field_policy = FieldPolicy.objects.create(
            content_type=ContentType.objects.get_for_model(Policy),
            name="Required field policy",
            rule={},
        )
        relation_field = ApplicationField.objects.get(
            content_type=ContentType.objects.get_for_model(FieldPolicy),
            field="policies",
        )
        layout = FieldLayout(
            rows=[
                LayoutRow(
                    title="Inline rows",
                    columns=1,
                    items=[
                        LayoutItem(
                            id=str(relation_field.pk),
                            colspan=1,
                            config={"inline_fields": ["description", "name", "row_policy"]},
                        )
                    ],
                )
            ]
        )

        with self.assertRaises(ValidationError) as exc_info:
            save_submitted_one_to_many_fields(
                parent_object=field_policy,
                layout=layout,
                submitted_data={
                    "policies__0__id": "",
                    "policies__0__description": "Missing required fields",
                    "policies__0__name": "",
                    "policies__0__row_policy": "",
                },
                user=self.admin_user,
            )

        self.assertTrue(
            any("Policies row 0, Name:" in message for message in exc_info.exception.messages)
        )
        self.assertTrue(
            any("Policies row 0, Row policy:" in message for message in exc_info.exception.messages)
        )
