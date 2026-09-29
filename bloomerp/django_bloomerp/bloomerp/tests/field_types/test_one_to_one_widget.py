"""Verify one-to-one widget selection through application-field form factories."""

from unittest.mock import patch

from django import forms
from django.contrib.auth import get_user_model
from django.db import models
from django.http import QueryDict
from django.test import SimpleTestCase

from bloomerp.forms.model_form import bloomerp_modelform_factory
from bloomerp.models.application_field import ApplicationField
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels
from bloomerp.tests.utils.dynamic_models import create_test_models
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget


class TestOneToOneWidget(SimpleTestCase):
    """One-to-one form fields use the single-object foreign-field picker."""

    def test_application_field_uses_foreign_widget(self) -> None:
        """
        Use case: A one-to-one application field builds its widget and form field.
        Expected result: Both use the foreign picker with scalar submitted values.
        """
        # 1. Supply a real Django relation without creating database records.
        related_model = get_user_model()
        model_field = models.OneToOneField(
            related_model,
            on_delete=models.SET_NULL,
            blank=True,
            null=True,
            limit_choices_to={"is_staff": True},
        )
        model_field.set_attributes_from_name("owner")
        application_field = ApplicationField(
            field="owner",
            field_type="OneToOneField",
            meta={"data-test": "owner-picker"},
        )

        # 2. Exercise both public widget construction paths.
        with (
            patch.object(application_field, "_get_model_field", return_value=model_field),
            patch.object(application_field, "get_related_model", return_value=related_model),
        ):
            widget = application_field.get_widget()
            form_field = application_field.get_form_field()

        # 3. Retain Django validation and the source metadata for choice limits.
        self.assertIsInstance(form_field, forms.ModelChoiceField)
        self.assertFalse(form_field.required)
        self.assertEqual(form_field.limit_choices_to, {"is_staff": True})
        self.assertIs(form_field.queryset.model, related_model)
        for picker in (widget, form_field.widget):
            with self.subTest(path=type(picker).__name__):
                self.assertIsInstance(picker, ForeignFieldWidget)
                self.assertIs(picker.model, related_model)
                self.assertIs(picker.source_field, application_field)
                self.assertFalse(picker.is_m2m)
                self.assertEqual(picker.attrs["data-test"], "owner-picker")
                self.assertEqual(
                    picker.value_from_datadict(QueryDict("owner=42"), {}, "owner"),
                    "42",
                )
                self.assertEqual(
                    picker.value_from_datadict(QueryDict("owner="), {}, "owner"),
                    "",
                )


class TestNonPrimaryOneToOneWidget(BaseBloomerpTestCaseWithModels):
    """Test model-form target values without altering the shared picker contract."""

    auto_create_customers = False

    @classmethod
    def setUpClass(cls) -> None:
        """Create a model whose one-to-one relation stores a unique username."""
        super().setUpClass()
        cls.OwnerModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "OneToOnePickerOwner": {
                    "owner": models.OneToOneField(
                        get_user_model(),
                        to_field="username",
                        on_delete=models.SET_NULL,
                        related_name="one_to_one_picker_owner",
                        null=True,
                        blank=True,
                        limit_choices_to={"is_staff": True},
                    ),
                },
            },
            use_bloomerp_base=True,
        )["OneToOnePickerOwner"]

    def test_model_form_renders_and_saves_target_relation(self) -> None:
        """
        Use case: An existing relation stores a username and the picker submits IDs.
        Expected result: Initial and bound values show the correct record and save usernames.
        """
        # 1. Make a username collide with another user's primary key.
        self.admin_user.username = "original-owner"
        self.admin_user.save()
        self.normal_user.username = str(self.admin_user.pk)
        self.normal_user.save()
        record = self.OwnerModel.objects.create(owner=self.admin_user)
        form_class = bloomerp_modelform_factory(self.OwnerModel, fields=["owner"])

        # 2. Stored usernames become IDs only for initial display.
        initial_form = form_class(instance=record)
        self.assertIsInstance(initial_form.fields["owner"].widget, ForeignFieldWidget)
        self.assertEqual(initial_form["owner"].value(), self.admin_user.pk)
        self.assertFalse(initial_form.fields["owner"].has_changed(
            self.admin_user.username, str(self.admin_user.pk),
        ))
        unchanged_form = form_class(data={"owner": str(self.admin_user.pk)}, instance=record)
        self.assertEqual(unchanged_form["owner"].value(), str(self.admin_user.pk))
        self.assertIn(
            f'data-value="{self.admin_user.pk}"',
            str(unchanged_form["owner"]),
        )
        self.assertTrue(unchanged_form.is_valid(), unchanged_form.errors)
        self.assertEqual(unchanged_form.cleaned_data["owner"], self.admin_user)

        # 3. A new picker selection persists the model's unique target value.
        changed_form = form_class(data={"owner": str(self.normal_user.pk)}, instance=record)
        self.assertTrue(changed_form.is_valid(), changed_form.errors)
        changed_form.save()
        record.refresh_from_db()
        self.assertEqual(record.owner_id, self.normal_user.username)
        self.assertEqual(record.owner, self.normal_user)

        # 4. Disabled fields retain stored values, and optional fields can clear.
        disabled_form = form_class(data={"owner": str(self.admin_user.pk)}, instance=record)
        disabled_form.fields["owner"].disabled = True
        self.assertEqual(disabled_form["owner"].value(), self.normal_user.pk)
        self.assertTrue(disabled_form.is_valid(), disabled_form.errors)
        self.assertEqual(disabled_form.cleaned_data["owner"], self.normal_user)
        cleared_form = form_class(data={"owner": ""}, instance=record)
        self.assertTrue(cleared_form.is_valid(), cleared_form.errors)
        cleared_form.save()
        record.refresh_from_db()
        self.assertIsNone(record.owner_id)

    def test_rejects_invalid_picker_ids_and_used_targets(self) -> None:
        """
        Use case: An invalid picker ID matches a username or a target is already linked.
        Expected result: Neither selection bypasses primary-key or one-to-one validation.
        """
        # 1. A target value cannot be submitted as an unrelated primary key.
        self.normal_user.username = "999999999"
        self.normal_user.save()
        form_class = bloomerp_modelform_factory(self.OwnerModel, fields=["owner"])
        invalid_form = form_class(data={"owner": self.normal_user.username})
        self.assertFalse(invalid_form.is_valid())
        self.assertEqual(invalid_form.errors.as_data()["owner"][0].code, "invalid_choice")

        # 2. Django still enforces unique ownership against the target column.
        self.OwnerModel.objects.create(owner=self.normal_user)
        duplicate_form = form_class(data={"owner": str(self.normal_user.pk)})
        self.assertFalse(duplicate_form.is_valid())
        self.assertEqual(duplicate_form.errors.as_data()["owner"][0].code, "unique")

        # 3. Choice limits remain available and enforced by generated model forms.
        excluded_user = get_user_model().objects.create(username="excluded-owner", is_staff=False)
        limited_form = form_class(data={"owner": str(excluded_user.pk)})
        self.assertEqual(limited_form.fields["owner"].limit_choices_to, {"is_staff": True})
        self.assertFalse(limited_form.is_valid())
        self.assertEqual(limited_form.errors.as_data()["owner"][0].code, "invalid_choice")

    def test_reverse_nonprimary_relation_uses_picker_without_formfield(self) -> None:
        """
        Use case: The reverse of a non-primary one-to-one relation is registered.
        Expected result: Widget construction succeeds without calling reverse formfield.
        """
        # 1. Resolve the reverse application field registered for the user model.
        application_field = ApplicationField.get_for_model(get_user_model()).get(
            field="one_to_one_picker_owner",
        )

        # 2. Reverse relations render a picker but have no writable Django form field.
        self.assertIsInstance(application_field.get_widget(), ForeignFieldWidget)
        self.assertIsNone(application_field.get_form_field())
