from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django import forms
from django.db import models
from django.db import connection
from django.http import QueryDict
from django.utils.datastructures import MultiValueDict

from bloomerp.models.base_bloomerp_model import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.access_control.field_policy import FieldPolicy
from bloomerp.models.access_control.policy import Policy
from bloomerp.models.access_control.row_policy import RowPolicy
from bloomerp.models.access_control.row_policy_rule import RowPolicyRule
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.files.file import File
from bloomerp.models.forms.form import Form as BloomerpForm
from bloomerp.models.forms.form_submission import FormSubmission
from bloomerp.services.sectioned_layout_services import (
    build_crud_layout_field_context,
    get_available_layout_fields,
)
from bloomerp.services.form_services import FormManager
from bloomerp.services.one_to_many_field_services import (
    save_submitted_one_to_many_fields,
)
from bloomerp.field_types import FieldType, Lookup
from bloomerp.form_fields.address_field import AddressFormField, AddressValue
from bloomerp.form_fields.files_relation_field import FilesCleanedData
from bloomerp.form_fields.one_to_many_field import OneToManyCleanedData, OneToManyField
from bloomerp.form_fields.phone_number_field import PhoneNumberFormField
from bloomerp.form_fields.week_field import WeekFormField, WeekValue
from bloomerp.forms.model_form import (
    bloomerp_modelform_factory,
    get_model_form_application_fields,
)
from bloomerp.model_fields.address_field import AddressField
from bloomerp.model_fields.phone_number_field import PhoneNumberField
from bloomerp.model_fields.week_field import WeekField
from bloomerp.tests.base import BaseBloomerpModelTestCase
from bloomerp.tests.utils.dynamic_models import create_test_models
from bloomerp.widgets.address_widget import AddressWidget
from bloomerp.widgets.code_editor_widget import CodeEditorWidget
from bloomerp.widgets.object_files_widget import ObjectFilesWidget
from bloomerp.widgets.one_to_many_field_widget import OneToManyFieldWidget
from bloomerp.widgets.phone_number_widget import PhoneNumberWidget
from bloomerp.widgets.week_widget import WeekWidget


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
        cls.CustomerRelationModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "CustomerRelation": {
                    "customer": models.ForeignKey(
                        cls.CustomerModel,
                        on_delete=models.SET_NULL,
                        related_name="nullable_relations",
                        blank=True,
                        null=True,
                    ),
                    "__str__": lambda self: "Customer relation",
                }
            },
            use_bloomerp_base=True,
        )["CustomerRelation"]
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
        cls.AddressRecordModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "AddressRecord": {
                    "address": AddressField(blank=True, null=True),
                    "__str__": lambda self: "Address record",
                }
            },
            use_bloomerp_base=True,
        )["AddressRecord"]
        cls.WeekRecordModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "WeekRecord": {
                    "week": WeekField(blank=True, null=True),
                    "__str__": lambda self: str(self.week or ""),
                }
            },
            use_bloomerp_base=True,
        )["WeekRecord"]

    def test_pk_application_field_returns_widget(self):
        content_type = ContentType.objects.get_for_model(Policy)
        application_field = ApplicationField.objects.get(
            content_type=content_type,
            field="pk",
        )

        widget = application_field.get_widget()

        self.assertIsNotNone(widget)

    def test_resolve_for_content_type_accepts_name_and_application_field(self):
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        application_field = ApplicationField.objects.get(
            content_type=content_type,
            field="first_name",
        )

        self.assertEqual(
            ApplicationField.resolve_for_content_type(content_type, "first_name"),
            application_field,
        )
        self.assertEqual(
            ApplicationField.resolve_for_content_type(content_type, application_field),
            application_field,
        )

    def test_resolve_for_content_type_rejects_field_from_another_model(self):
        customer_content_type = ContentType.objects.get_for_model(self.CustomerModel)
        policy_field = ApplicationField.objects.filter(
            content_type=ContentType.objects.get_for_model(Policy),
        ).first()

        with self.assertRaisesMessage(ValueError, "belongs to a different content type"):
            ApplicationField.resolve_for_content_type(
                customer_content_type,
                policy_field,
            )

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

    def test_files_application_field_uses_files_relation_field_type(self):
        application_field = ApplicationField.objects.get(
            content_type=ContentType.objects.get_for_model(self.CustomerModel),
            field="files",
        )

        self.assertEqual(application_field.field_type, FieldType.FILES_RELATION_FIELD.id)
        self.assertIsInstance(application_field.get_widget(), ObjectFilesWidget)
        self.assertTrue(application_field.get_field_type_enum().value.editable_without_form_field)

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

    def test_address_field_type_uses_address_field_parts(self):
        field_type = FieldType.ADDRESS_FIELD.value

        self.assertEqual(field_type.id, "AddressField")
        self.assertIs(field_type.model_field_cls, AddressField)
        self.assertIs(field_type.form_field_cls, AddressFormField)
        self.assertIs(field_type.widget_cls, AddressWidget)
        self.assertEqual(field_type.lookups, [Lookup.ADDRESS_ADVANCED])

    def test_week_field_type_uses_week_field_parts(self):
        field_type = FieldType.WEEK_FIELD.value

        self.assertEqual(field_type.id, "WeekField")
        self.assertIs(field_type.model_field_cls, WeekField)
        self.assertIs(field_type.form_field_cls, WeekFormField)
        self.assertIs(field_type.widget_cls, WeekWidget)
        self.assertEqual(field_type.default_model_field_args["max_length"], 8)
        self.assertIn(Lookup.EQUALS, field_type.lookups)

    def test_address_form_field_normalizes_structured_value(self):
        form_field = AddressFormField()

        value = form_field.clean(
            [
                " Main street 1 ",
                "",
                " 1000 ",
                " Brussels ",
                "",
                "BE",
            ]
        )

        self.assertIsInstance(value, AddressValue)
        self.assertEqual(
            value,
            {
                "street_1": "Main street 1",
                "street_2": "",
                "postal_code": "1000",
                "city": "Brussels",
                "state": "",
                "country": "BE",
            },
        )
        self.assertEqual(str(value), "Main street 1, 1000 Brussels, Belgium")

    def test_address_form_field_rejects_unknown_country_code(self):
        form_field = AddressFormField()

        with self.assertRaises(ValidationError):
            form_field.clean(
                [
                    "Main street 1",
                    "",
                    "1000",
                    "Brussels",
                    "",
                    "ZZZ",
                ]
            )

    def test_address_model_field_formfield_uses_address_widget(self):
        model_field = AddressField()
        form_field = model_field.formfield()

        self.assertIsInstance(form_field, AddressFormField)
        self.assertIsInstance(form_field.widget, AddressWidget)

    def test_address_model_field_to_python_returns_string_renderable_value(self):
        model_field = AddressField()

        value = model_field.to_python(
            {
                "street_1": "Main street 1",
                "street_2": "",
                "postal_code": "1000",
                "city": "Brussels",
                "state": "",
                "country": "BE",
            }
        )

        self.assertIsInstance(value, AddressValue)
        self.assertEqual(str(value), "Main street 1, 1000 Brussels, Belgium")

    def test_stale_json_field_metadata_uses_address_widget_for_address_field(self):
        content_type = ContentType.objects.get_for_model(self.AddressRecordModel)
        application_field = ApplicationField.objects.get(
            content_type=content_type,
            field="address",
        )
        application_field.field_type = FieldType.JSON_FIELD.id

        form_field = application_field.get_form_field()

        self.assertEqual(application_field.get_field_type_enum(), FieldType.ADDRESS_FIELD)
        self.assertIsInstance(form_field, AddressFormField)
        self.assertIsInstance(form_field.widget, AddressWidget)

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

    def test_week_form_field_returns_template_friendly_value(self):
        form_field = WeekFormField()

        value = form_field.clean("2026-W26")

        self.assertIsInstance(value, WeekValue)
        self.assertEqual(value.year, 2026)
        self.assertEqual(value.week, 26)
        self.assertEqual(str(value), "2026-W26")

    def test_week_form_field_rejects_invalid_week(self):
        form_field = WeekFormField()

        with self.assertRaises(ValidationError):
            form_field.clean("2026-W54")

    def test_week_model_field_formfield_uses_week_widget(self):
        model_field = WeekField()
        form_field = model_field.formfield()

        self.assertIsInstance(form_field, WeekFormField)
        self.assertIsInstance(form_field.widget, WeekWidget)
        self.assertEqual(form_field.widget.input_type, "week")
        self.assertEqual(str(form_field.clean("2026-W26")), "2026-W26")

    def test_week_model_field_exposes_database_type(self):
        model_field = WeekField(max_length=8)

        self.assertEqual(
            model_field.db_type(connection),
            models.CharField(max_length=8).db_type(connection),
        )

    def test_week_model_field_round_trips_string_renderable_value(self):
        record = self.WeekRecordModel.objects.create(week="2026-W26")

        record = self.WeekRecordModel.objects.get(pk=record.pk)

        self.assertIsInstance(record.week, WeekValue)
        self.assertEqual(record.week.year, 2026)
        self.assertEqual(record.week.week, 26)
        self.assertEqual(str(record.week), "2026-W26")

    def test_week_application_field_widget_uses_week_input(self):
        content_type = ContentType.objects.get_for_model(self.WeekRecordModel)
        application_field = ApplicationField.objects.get(
            content_type=content_type,
            field="week",
        )

        form_field = application_field.get_form_field()

        self.assertEqual(application_field.get_field_type_enum(), FieldType.WEEK_FIELD)
        self.assertIsInstance(form_field, WeekFormField)
        self.assertIsInstance(form_field.widget, WeekWidget)
        self.assertEqual(form_field.widget.input_type, "week")

    def test_week_layout_render_uses_week_input_with_input_class(self):
        content_type = ContentType.objects.get_for_model(self.WeekRecordModel)
        application_field = ApplicationField.objects.get(
            content_type=content_type,
            field="week",
        )
        form_field = application_field.get_form_field()
        form_cls = type("WeekForm", (forms.Form,), {"week": form_field})
        form = form_cls(initial={"week": "2026-W26"})

        context = build_crud_layout_field_context(
            application_field=application_field,
            bound_field=form["week"],
        )

        self.assertIn('type="week"', context["input"])
        self.assertIn('class="input w-full"', context["input"])

    def test_phone_number_model_field_exposes_database_type(self):
        model_field = PhoneNumberField(max_length=30)

        self.assertEqual(
            model_field.db_type(connection),
            models.CharField(max_length=30).db_type(connection),
        )

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

    def test_address_model_field_exposes_database_type(self):
        model_field = AddressField()

        self.assertEqual(
            model_field.db_type(connection),
            models.JSONField().db_type(connection),
        )

    def test_property_backed_application_field_returns_no_form_field(self):
        content_type = ContentType.objects.get_for_model(RowPolicyRule)
        application_field = ApplicationField.objects.get(
            content_type=content_type,
            field="content_type",
        )

        form_field = application_field.get_form_field()

        self.assertIsNone(form_field)

    def test_model_form_factory_declares_property_as_read_only_form_field(self):
        content_type = ContentType.objects.get_for_model(RowPolicyRule)
        application_field = ApplicationField.objects.get(
            content_type=content_type,
            field="content_type",
        )
        target_content_type = ContentType.objects.get_for_model(Policy)
        row_policy = RowPolicy.objects.create(
            content_type=target_content_type,
            name="Property form field",
        )
        row_policy_rule = RowPolicyRule.objects.create(
            row_policy=row_policy,
            rule={
                "connector": "OR",
                "conditions": [
                    {
                        "application_field_id": str(
                            ApplicationField.objects.get(
                                content_type=target_content_type,
                                field="name",
                            ).pk
                        ),
                        "operator": Lookup.EQUALS.value.id,
                        "value": "Policy",
                    }
                ],
            },
        )

        form_class = bloomerp_modelform_factory(
            RowPolicyRule,
            fields=[application_field.field],
        )
        form = form_class(instance=row_policy_rule)

        self.assertIn("content_type", form.fields)
        self.assertTrue(form.fields["content_type"].disabled)
        self.assertEqual(form.initial["content_type"], row_policy_rule.content_type)

    def test_create_form_fields_include_properties_but_exclude_managed_fields(self):
        content_type = ContentType.objects.get_for_model(RowPolicyRule)
        property_field = ApplicationField.objects.get(
            content_type=content_type,
            field="content_type",
        )
        managed_field = ApplicationField.objects.get(
            content_type=content_type,
            field="id",
        )

        fields = get_model_form_application_fields(
            RowPolicyRule,
            [property_field, managed_field],
            exclude_auto_managed=True,
        )

        self.assertTrue(fields.filter(pk=property_field.pk).exists())
        self.assertFalse(fields.filter(pk=managed_field.pk).exists())

    def test_layout_form_disables_system_fields_but_keeps_files_enabled(self):
        form_class = bloomerp_modelform_factory(
            self.CustomerModel,
            fields=[
                "id",
                "pk",
                "datetime_created",
                "datetime_updated",
                "created_by",
                "updated_by",
                "comments",
                "files",
            ],
        )

        form = form_class()

        for field_name in {
            "id",
            "pk",
            "datetime_created",
            "datetime_updated",
            "created_by",
            "updated_by",
            "comments",
        }:
            self.assertTrue(form.fields[field_name].disabled, field_name)
        self.assertFalse(form.fields["files"].disabled)

    def test_disabled_system_field_ignores_submitted_value(self):
        customer = self.CustomerModel.objects.create(
            first_name="Ada",
            last_name="Lovelace",
            age=36,
        )
        original_id = customer.id
        form_class = bloomerp_modelform_factory(
            self.CustomerModel,
            fields=["first_name", "id"],
        )
        form = form_class(
            data={
                "first_name": "Grace",
                "id": "00000000-0000-0000-0000-000000000001",
            },
            instance=customer,
        )

        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()

        self.assertEqual(saved.id, original_id)
        self.assertEqual(saved.first_name, "Grace")

    def test_create_layout_fields_include_permitted_system_fields(self):
        content_type = ContentType.objects.get_for_model(self.CustomerModel)

        available_fields = get_available_layout_fields(
            content_type=content_type,
            user=self.admin_user,
            layout_kind="create",
        )
        available_ids = {field["id"] for field in available_fields}

        for field_name in {
            "id",
            "pk",
            "datetime_created",
            "datetime_updated",
            "created_by",
            "updated_by",
            "comments",
            "files",
        }:
            application_field = ApplicationField.objects.get(
                content_type=content_type,
                field=field_name,
            )
            self.assertIn(application_field.pk, available_ids, field_name)

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
                "connector": "OR",
                "conditions": [
                    {
                        "application_field_id": str(target_field.pk),
                        "operator": Lookup.EQUALS.value.id,
                        "value": "Policy",
                    }
                ],
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

    def test_model_form_factory_declares_one_to_many_application_fields(self):
        customer = self.create_customer("Inline", "Viewer", 38)
        self.CustomerLineModel.objects.create(
            customer=customer,
            description="Existing line",
            hours="1.50",
        )

        form_class = bloomerp_modelform_factory(
            self.CustomerModel,
            fields=["first_name", "lines"],
        )
        form = form_class(instance=customer)

        self.assertIn("lines", form.fields)
        self.assertNotIn("lines", form._meta.fields)
        self.assertIsInstance(form.fields["lines"], OneToManyField)
        self.assertIsInstance(form.fields["lines"].widget, OneToManyFieldWidget)
        self.assertIn("Existing line", form["lines"].as_widget())

    def test_one_to_many_form_field_returns_structured_changes(self):
        customer = self.create_customer("Inline", "Editor", 39)
        existing_line = self.CustomerLineModel.objects.create(
            customer=customer,
            description="Old description",
            hours="1.00",
        )
        deleted_line = self.CustomerLineModel.objects.create(
            customer=customer,
            description="Delete me",
            hours="2.00",
        )
        form_class = bloomerp_modelform_factory(
            self.CustomerModel,
            fields=["first_name", "lines"],
        )
        form = form_class(
            data={
                "first_name": customer.first_name,
                "lines__0__id": str(existing_line.pk),
                "lines__0__description": "Updated description",
                "lines__0__hours": "3.50",
                "lines__1__id": "",
                "lines__1__description": "New line",
                "lines__1__hours": "4.25",
                "lines__2__id": str(deleted_line.pk),
                "lines__2__DELETE": "1",
            },
            instance=customer,
        )

        self.assertTrue(form.is_valid(), form.errors)
        result = form.cleaned_data["lines"]
        self.assertIsInstance(result, OneToManyCleanedData)
        self.assertEqual(len(result.to_save), 2)
        self.assertEqual(result.to_save[0].pk, existing_line.pk)
        self.assertEqual(result.to_save[0].description, "Updated description")
        self.assertTrue(result.to_save[1]._state.adding)
        self.assertEqual(result.to_save[1].description, "New line")
        self.assertEqual(result.to_delete, [deleted_line])

        cleaned_o2m_data = form.get_cleaned_o2m_data()
        self.assertEqual(set(cleaned_o2m_data), {"lines"})
        updated_entry, created_entry, deleted_entry = cleaned_o2m_data["lines"]
        self.assertIs(updated_entry.object, result.to_save[0])
        self.assertTrue(updated_entry.changed)
        self.assertFalse(updated_entry.created)
        self.assertFalse(updated_entry.deleted)
        self.assertIs(created_entry.object, result.to_save[1])
        self.assertTrue(created_entry.created)
        self.assertFalse(created_entry.changed)
        self.assertFalse(created_entry.deleted)
        self.assertEqual(deleted_entry.object.pk, deleted_line.pk)
        self.assertTrue(deleted_entry.deleted)
        self.assertFalse(deleted_entry.created)
        self.assertFalse(deleted_entry.changed)

        serialized_data = form.serialize_cleaned_data()
        self.assertEqual(serialized_data["lines"][0]["description"], "Updated description")
        self.assertEqual(serialized_data["lines"][2]["DELETE"], True)

        existing_line.refresh_from_db()
        self.assertEqual(existing_line.description, "Old description")
        self.assertTrue(self.CustomerLineModel.objects.filter(pk=deleted_line.pk).exists())

        form.save()
        form.save_o2m()

        existing_line.refresh_from_db()
        self.assertEqual(existing_line.description, "Updated description")
        self.assertFalse(self.CustomerLineModel.objects.filter(pk=deleted_line.pk).exists())
        self.assertTrue(
            self.CustomerLineModel.objects.filter(
                customer=customer,
                description="New line",
                hours="4.25",
            ).exists()
        )

    def test_model_form_save_persists_structured_file_values(self):
        customer = self.create_customer("File", "Owner", 42)
        uploaded_file = SimpleUploadedFile(
            "agreement.pdf",
            b"agreement content",
            content_type="application/pdf",
        )
        form_class = bloomerp_modelform_factory(
            self.CustomerModel,
            fields=["first_name", "files"],
        )
        form = form_class(
            data={"first_name": customer.first_name},
            files=MultiValueDict({"files": [uploaded_file]}),
            instance=customer,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsInstance(form.cleaned_data["files"], FilesCleanedData)

        saved_customer = form.save()

        attached_file = File.objects.get(name="agreement.pdf")
        self.assertEqual(attached_file.object_id, str(saved_customer.pk))
        self.assertTrue(attached_file.persisted)

    def test_model_form_deserializes_json_compatible_values(self):
        customer = self.create_customer("Deserialize", "Values", 43)
        form_class = bloomerp_modelform_factory(
            self.CustomerModel,
            fields=["age"],
        )
        form = form_class(instance=customer)

        cleaned_data = form.deserialize_cleaned_data({"age": "44"})

        self.assertEqual(cleaned_data, {"age": 44})

    def test_model_form_round_trips_serialized_cleaned_data(self):
        customer = self.create_customer("Round", "Trip", 43)
        form_class = bloomerp_modelform_factory(
            self.CustomerModel,
            fields=["first_name", "last_name", "age"],
        )
        source_form = form_class(
            data={
                "first_name": "Serialized",
                "last_name": "Customer",
                "age": "44",
            },
            instance=customer,
        )

        self.assertTrue(source_form.is_valid(), source_form.errors)

        restored_form = form_class.from_deserialized_data(
            source_form.serialize_cleaned_data(),
            instance=customer,
        )

        self.assertTrue(restored_form.is_bound)
        self.assertTrue(restored_form.is_valid(), restored_form.errors)
        self.assertEqual(
            restored_form.cleaned_data,
            source_form.cleaned_data,
        )
        self.assertEqual(restored_form["first_name"].value(), "Serialized")
        self.assertEqual(restored_form["age"].value(), 44)
        self.assertEqual(restored_form.instance.first_name, "Serialized")
        self.assertEqual(restored_form.instance.age, 44)

    def test_model_form_from_deserialized_data_preserves_validation_errors(self):
        form_class = bloomerp_modelform_factory(
            self.CustomerModel,
            fields=["first_name", "last_name", "age"],
        )

        restored_form = form_class.from_deserialized_data(
            {
                "first_name": "Invalid",
                "last_name": "Customer",
                "age": "not-an-integer",
            }
        )

        self.assertFalse(restored_form.is_valid())
        self.assertIn("age", restored_form.errors)

    def test_model_form_uses_initial_file_objects_for_deserialized_display(self):
        form_class = bloomerp_modelform_factory(
            self.CustomerModel,
            fields=["files"],
        )
        displayed_file = object()

        restored_form = form_class.from_deserialized_data(
            {"files": ["submitted.pdf"]},
            initial={"files": [displayed_file]},
        )

        self.assertEqual(restored_form["files"].value(), [displayed_file])

    def test_model_form_round_trips_structured_one_to_many_data(self):
        form_class = bloomerp_modelform_factory(
            self.CustomerModel,
            fields=["first_name", "last_name", "age", "lines"],
        )
        source_form = form_class(
            data={
                "first_name": "Structured",
                "last_name": "Customer",
                "age": "45",
                "lines__0__id": "",
                "lines__0__description": "Restored line",
                "lines__0__hours": "2.50",
            }
        )

        self.assertTrue(source_form.is_valid(), source_form.errors)

        restored_form = form_class.from_deserialized_data(
            source_form.serialize_cleaned_data()
        )

        self.assertTrue(restored_form.is_valid(), restored_form.errors)
        restored_lines = restored_form.cleaned_data["lines"]
        self.assertIsInstance(restored_lines, OneToManyCleanedData)
        self.assertEqual(restored_lines.to_save[0].description, "Restored line")
        self.assertEqual(
            restored_form["lines"].value()[0]["description"],
            "Restored line",
        )

        customer = restored_form.save()
        self.assertTrue(
            self.CustomerLineModel.objects.filter(
                customer=customer,
                description="Restored line",
                hours="2.50",
            ).exists()
        )

    def test_model_form_prepares_omitted_values_for_partial_update(self):
        customer = self.create_customer("Partial", "Update", 44)
        form_class = bloomerp_modelform_factory(
            self.CustomerModel,
            fields=["first_name", "last_name", "age"],
        )

        prepared_data = form_class.prepare_bound_data(
            QueryDict("age=45"),
            MultiValueDict(),
            customer,
            partial=True,
        )

        self.assertEqual(prepared_data["first_name"], "Partial")
        self.assertEqual(prepared_data["last_name"], "Update")
        self.assertEqual(prepared_data["age"], "45")

    def test_model_form_clears_foreign_key_when_partial_update_submits_empty_value(self):
        """
        Use case: A user removes a foreign-key relationship from an existing object.
        Expected result: The partial model form saves the relation as null.
        """

        # 1. Create an object with an existing nullable foreign-key relation.
        customer = self.create_customer("Related", "Customer", 44)
        relation = self.CustomerRelationModel.objects.create(customer=customer)
        form_class = bloomerp_modelform_factory(
            self.CustomerRelationModel,
            fields=["customer"],
        )

        # 2. Keep the empty foreign-key value explicitly in the submitted data.
        prepared_data = form_class.prepare_bound_data(
            QueryDict("customer=", mutable=True),
            MultiValueDict(),
            relation,
            partial=True,
        )

        # 3. Validate and save the partial update.
        form = form_class(data=prepared_data, instance=relation)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        # 4. Confirm the existing relationship was removed.
        relation.refresh_from_db()
        self.assertIsNone(relation.customer_id)

    def test_one_to_many_form_field_rejects_an_object_from_another_parent(self):
        customer = self.create_customer("First", "Parent", 40)
        other_customer = self.create_customer("Other", "Parent", 41)
        other_line = self.CustomerLineModel.objects.create(
            customer=other_customer,
            description="Private line",
            hours="1.00",
        )
        form_class = bloomerp_modelform_factory(
            self.CustomerModel,
            fields=["first_name", "lines"],
        )
        form = form_class(
            data={
                "first_name": customer.first_name,
                "lines__0__id": str(other_line.pk),
                "lines__0__description": "Stolen update",
                "lines__0__hours": "2.00",
            },
            instance=customer,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("Invalid related object", form.errors["lines"].as_text())

    def test_form_submission_includes_one_to_many_layout_rows(self):
        parent_content_type = ContentType.objects.get_for_model(self.CustomerModel)
        relation_field = ApplicationField.objects.get(
            content_type=parent_content_type,
            field="lines",
        )
        form_object = BloomerpForm.objects.create(
            name="Customer form",
            content_type=parent_content_type,
            layout=FieldLayout(
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
            ).model_dump(),
        )
        request = type(
            "Request",
            (),
            {
                "POST": {
                    "lines__0__id": "",
                    "lines__0__description": "Contract line",
                    "lines__0__hours": "3.75",
                }
            },
        )()

        response = FormManager(form_object).register_submission(
            {
                "first_name": "David",
                "last_name": "Bloomer",
            },
            request=request,
        )

        response.form_submission.refresh_from_db()
        self.assertEqual(
            response.form_submission.data,
            {
                "first_name": "David",
                "last_name": "Bloomer",
                "lines": [
                    {
                        "id": "",
                        "description": "Contract line",
                        "hours": "3.75",
                    }
                ],
            },
        )

    def test_form_submission_without_review_persists_object_and_one_to_many_rows(self):
        parent_content_type = ContentType.objects.get_for_model(self.CustomerModel)
        fields_by_name = {
            field.field: field
            for field in ApplicationField.objects.filter(
                content_type=parent_content_type,
                field__in=["first_name", "last_name", "age", "lines"],
            )
        }
        form_object = BloomerpForm.objects.create(
            name="Customer form",
            content_type=parent_content_type,
            requires_review=False,
            layout=FieldLayout(
                rows=[
                    LayoutRow(
                        title="Customer",
                        columns=2,
                        items=[
                            LayoutItem(id=str(fields_by_name["first_name"].pk)),
                            LayoutItem(id=str(fields_by_name["last_name"].pk)),
                            LayoutItem(id=str(fields_by_name["age"].pk)),
                            LayoutItem(
                                id=str(fields_by_name["lines"].pk),
                                colspan=2,
                                config={"inline_fields": ["description", "hours"]},
                            ),
                        ],
                    )
                ]
            ).model_dump(),
        )
        request = type(
            "Request",
            (),
            {
                "user": self.admin_user,
                "POST": {
                    "lines__0__id": "",
                    "lines__0__description": "Persisted line",
                    "lines__0__hours": "4.25",
                },
            },
        )()

        response = FormManager(form_object).register_submission(
            {
                "first_name": "Persisted",
                "last_name": "Customer",
                "age": "41",
            },
            request=request,
        )

        self.assertTrue(response.submitted)
        response.form_submission.refresh_from_db()
        self.assertTrue(response.form_submission.persisted)
        customer = self.CustomerModel.objects.get(first_name="Persisted")
        self.assertEqual(customer.last_name, "Customer")
        self.assertTrue(
            self.CustomerLineModel.objects.filter(
                customer=customer,
                description="Persisted line",
                hours="4.25",
            ).exists()
        )

    def test_form_submission_with_review_attaches_files_to_submission_then_persist_moves_to_object(self):
        parent_content_type = ContentType.objects.get_for_model(self.CustomerModel)
        form_submission_content_type = ContentType.objects.get_for_model(FormSubmission)
        fields_by_name = {
            field.field: field
            for field in ApplicationField.objects.filter(
                content_type=parent_content_type,
                field__in=["first_name", "last_name", "age", "files"],
            )
        }
        form_object = BloomerpForm.objects.create(
            name="Customer form",
            content_type=parent_content_type,
            requires_review=True,
            layout=FieldLayout(
                rows=[
                    LayoutRow(
                        title="Customer",
                        columns=2,
                        items=[
                            LayoutItem(id=str(fields_by_name["first_name"].pk)),
                            LayoutItem(id=str(fields_by_name["last_name"].pk)),
                            LayoutItem(id=str(fields_by_name["age"].pk)),
                            LayoutItem(id=str(fields_by_name["files"].pk)),
                        ],
                    )
                ]
            ).model_dump(),
        )
        uploaded_files = [
            SimpleUploadedFile(
                "submitted.pdf",
                b"submitted content",
                content_type="application/pdf",
            ),
            SimpleUploadedFile(
                "supporting.png",
                b"supporting content",
                content_type="image/png",
            ),
        ]
        request = type(
            "Request",
            (),
            {
                "user": self.admin_user,
                "POST": {},
            },
        )()
        manager = FormManager(form_object)
        form_class = manager.layout_form_cls()
        submitted_form = form_class(
            data={
                "first_name": "Reviewed",
                "last_name": "Customer",
                "age": "42",
            },
            files=MultiValueDict({"files": uploaded_files}),
        )
        self.assertTrue(submitted_form.is_valid(), submitted_form.errors)

        response = manager.register_submission(
            submitted_form,
            request=request,
        )

        self.assertTrue(response.submitted)
        submission = response.form_submission
        submission.refresh_from_db()
        attached_files = list(File.objects.filter(object_id=str(submission.pk)))
        self.assertEqual(len(attached_files), 2)
        self.assertEqual(
            {attached_file.name for attached_file in attached_files},
            {"submitted.pdf", "supporting.png"},
        )
        self.assertTrue(
            all(
                attached_file.content_type == form_submission_content_type
                for attached_file in attached_files
            )
        )
        self.assertEqual(
            submission.data["files"],
            ["submitted.pdf", "supporting.png"],
        )

        manager.persist_form_submission(submission, request=request)

        customer = self.CustomerModel.objects.get(first_name="Reviewed")
        for attached_file in attached_files:
            attached_file.refresh_from_db()
            self.assertEqual(attached_file.content_type, parent_content_type)
            self.assertEqual(attached_file.object_id, str(customer.pk))
            self.assertTrue(attached_file.persisted)

    def test_form_submission_without_review_moves_files_to_persisted_object_immediately(self):
        parent_content_type = ContentType.objects.get_for_model(self.CustomerModel)
        fields_by_name = {
            field.field: field
            for field in ApplicationField.objects.filter(
                content_type=parent_content_type,
                field__in=["first_name", "last_name", "age", "files"],
            )
        }
        form_object = BloomerpForm.objects.create(
            name="Customer form",
            content_type=parent_content_type,
            requires_review=False,
            layout=FieldLayout(
                rows=[
                    LayoutRow(
                        title="Customer",
                        columns=2,
                        items=[
                            LayoutItem(id=str(fields_by_name["first_name"].pk)),
                            LayoutItem(id=str(fields_by_name["last_name"].pk)),
                            LayoutItem(id=str(fields_by_name["age"].pk)),
                            LayoutItem(id=str(fields_by_name["files"].pk)),
                        ],
                    )
                ]
            ).model_dump(),
        )
        request = type(
            "Request",
            (),
            {
                "user": self.admin_user,
                "POST": {},
                "FILES": MultiValueDict(
                    {
                        "files": [
                            SimpleUploadedFile("immediate.pdf", b"immediate content", content_type="application/pdf")
                        ]
                    }
                ),
            },
        )()

        response = FormManager(form_object).register_submission(
            {
                "first_name": "Immediate",
                "last_name": "Customer",
                "age": "43",
            },
            request=request,
        )

        self.assertTrue(response.submitted)
        response.form_submission.refresh_from_db()
        self.assertTrue(response.form_submission.persisted)
        customer = self.CustomerModel.objects.get(first_name="Immediate")
        attached_file = File.objects.get(name="immediate.pdf")
        self.assertEqual(attached_file.content_type, parent_content_type)
        self.assertEqual(attached_file.object_id, str(customer.pk))
        self.assertEqual(response.form_submission.data["files"], [str(attached_file.id)])

    def test_form_initial_payload_persists_hidden_model_fields(self):
        parent_content_type = ContentType.objects.get_for_model(self.CustomerModel)
        fields_by_name = {
            field.field: field
            for field in ApplicationField.objects.filter(
                content_type=parent_content_type,
                field__in=["first_name", "last_name"],
            )
        }
        form_object = BloomerpForm.objects.create(
            name="Customer form",
            content_type=parent_content_type,
            requires_review=False,
            initial_payload={"age": 41},
            layout=FieldLayout(
                rows=[
                    LayoutRow(
                        title="Customer",
                        columns=2,
                        items=[
                            LayoutItem(id=str(fields_by_name["first_name"].pk)),
                            LayoutItem(id=str(fields_by_name["last_name"].pk)),
                        ],
                    )
                ]
            ).model_dump(),
        )
        request = type(
            "Request",
            (),
            {
                "user": self.admin_user,
                "POST": {},
            },
        )()

        response = FormManager(form_object).register_submission(
            {
                "first_name": "Hidden",
                "last_name": "Default",
            },
            request=request,
        )

        self.assertTrue(response.submitted)
        response.form_submission.refresh_from_db()
        self.assertEqual(response.form_submission.data["age"], 41)
        self.assertTrue(response.form_submission.persisted)
        customer = self.CustomerModel.objects.get(first_name="Hidden")
        self.assertEqual(customer.age, 41)

    def test_visible_initial_payload_is_available_as_form_initial_data(self):
        parent_content_type = ContentType.objects.get_for_model(self.CustomerModel)
        fields_by_name = {
            field.field: field
            for field in ApplicationField.objects.filter(
                content_type=parent_content_type,
                field__in=["first_name", "last_name"],
            )
        }
        form_object = BloomerpForm.objects.create(
            name="Customer form",
            content_type=parent_content_type,
            initial_payload={
                "first_name": "Visible",
                "age": 41,
            },
            layout=FieldLayout(
                rows=[
                    LayoutRow(
                        title="Customer",
                        columns=2,
                        items=[
                            LayoutItem(id=str(fields_by_name["first_name"].pk)),
                            LayoutItem(id=str(fields_by_name["last_name"].pk)),
                        ],
                    )
                ]
            ).model_dump(),
        )

        initial_data = FormManager(form_object).get_initial_form_data()

        self.assertEqual(initial_data, {"first_name": "Visible"})

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


class FormCleanTestCase(BaseBloomerpModelTestCase):
    auto_create_customers = False
    auto_create_users = False
    create_foreign_models = True

    def test_form_clean_resets_layout_and_initial_payload_when_content_type_changes(self):
        customer_content_type = ContentType.objects.get_for_model(self.CustomerModel)
        country_content_type = ContentType.objects.get_for_model(self.CountryModel)
        customer_first_name_field = ApplicationField.objects.get(
            content_type=customer_content_type,
            field="first_name",
        )
        country_name_field = ApplicationField.objects.get(
            content_type=country_content_type,
            field="name",
        )
        form_object = BloomerpForm(
            name="Customer form",
            content_type=customer_content_type,
            initial_payload={"age": 41},
            layout=FieldLayout(
                rows=[
                    LayoutRow(
                        title="Customer",
                        columns=1,
                        items=[LayoutItem(id=str(customer_first_name_field.pk))],
                    )
                ]
            ).model_dump(),
        )
        BloomerpForm.objects.bulk_create([form_object])
        form_object = BloomerpForm.objects.get(name="Customer form")

        form_object.content_type = country_content_type
        form_object.full_clean()

        layout_item_ids = {
            str(item.id)
            for row in form_object.layout_obj.rows
            for item in row.items
        }
        self.assertEqual(form_object.initial_payload, {})
        self.assertNotIn(str(customer_first_name_field.pk), layout_item_ids)
        self.assertIn(str(country_name_field.pk), layout_item_ids)
