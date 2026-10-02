"""Verify one-to-one widget selection through application-field form factories."""

from unittest.mock import patch

from bloomerp.models.application_field import ApplicationField
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget
from django import forms
from django.contrib.auth import get_user_model
from django.db import models
from django.http import QueryDict
from django.test import SimpleTestCase


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
