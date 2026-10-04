"""Check metadata defaults and overrides in display-option factories."""

from unittest.mock import patch

from django import forms
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from bloomerp.field_types.display_options import FieldDisplayOption
from bloomerp.models import ApplicationField, Todo
from bloomerp.field_types.builtins.text import CHAR_FIELD
from bloomerp.field_types.registry import FieldContext


def plain_factory(application_field: ApplicationField) -> forms.Field:
    """Supply a field that relies on display-option metadata."""
    return forms.CharField()


def override_factory(application_field: ApplicationField) -> forms.Field:
    """Supply explicit factory metadata that should remain available."""
    return forms.CharField(
        label="Factory label", help_text="Factory help", required=True
    )


class TestDisplayOptionFactories(SimpleTestCase):
    """Pure factory metadata checks outside the request scenario abstraction."""

    def test_metadata_defaults_and_overrides(self) -> None:
        """
        Use case: Factories supply field-specific behavior and optional metadata overrides.
        Expected result: Common metadata is applied once and explicit overrides survive.
        """
        # 1. Build a fresh editor with common metadata from its option.
        source = ApplicationField()
        option = FieldDisplayOption(
            id="label",
            label="Option label",
            help_text="Option help",
            form_factory=plain_factory,
        )
        field = option.build_form_field(source)
        self.assertEqual(
            (field.label, field.help_text, field.required),
            ("Option label", "Option help", False),
        )
        self.assertFalse(field.widget.is_required)
        self.assertIsNot(field, option.build_form_field(source))

        # 2. Preserve factory label/help overrides and opt into its required setting.
        override = FieldDisplayOption(
            id="label",
            label="Option label",
            help_text="Option help",
            required=None,
            form_factory=override_factory,
        )
        field = override.build_form_field(source)
        self.assertEqual(
            (field.label, field.help_text, field.required),
            ("Factory label", "Factory help", True),
        )

    def test_removed_choices_use_a_text_editor(self) -> None:
        """
        Use case: A previously colored choice field becomes an ordinary text field.
        Expected result: Stored color settings are harmless and the text editor works.
        """
        # 1. Build a configured choice editor through the real field type factory.
        source = ApplicationField(
            field_type="CharField",
            field="status",
            content_type=ContentType(app_label="bloomerp", model="todo"),
            meta={"choices": [["completed", "Completed"]]},
        )
        config = {"choice_colors": {"completed": "#00ff00"}}
        markup = CHAR_FIELD.widget_factory(
            FieldContext(
                application_field=source, attrs=source.meta, layout_config=config
            )
        ).render("status", "completed")
        self.assertIn('data-choice-color="#00ff00"', markup)
        self.assertIn("<select", markup)

        # 2. Refresh metadata after choices disappear and keep the old layout config.
        source.meta = {"choices": []}
        markup = CHAR_FIELD.widget_factory(
            FieldContext(
                application_field=source, attrs=source.meta, layout_config=config
            )
        ).render("status", "Free text")
        self.assertIn('type="text"', markup)
        self.assertIn('value="Free text"', markup)
        self.assertNotIn("<select", markup)
        self.assertNotIn("choice-color", markup)

    def test_blank_choice_matches_model_field_validation(self) -> None:
        """
        Use case: Required and optional choice fields use the same widget factory.
        Expected result: Only fields permitting blank input gain an empty option.
        """
        # 1. Resolve the real required Todo status field without database queries.
        model_field = Todo._meta.get_field("status")
        source = ApplicationField(
            field_type="CharField",
            field="status",
            content_type=ContentType(app_label="bloomerp", model="todo"),
            meta={"choices": model_field.choices},
        )
        context = FieldContext(application_field=source, attrs=source.meta)
        widget = CHAR_FIELD.widget_factory(context)
        self.assertNotIn("", [str(value) for value, _label in widget.choices])
        self.assertNotIn('value=""', widget.render("status", model_field.default))
        with self.assertRaises(ValidationError):
            model_field.formfield().clean("")

        # 2. Make the same CharField optional and retain its configured default.
        with patch.object(model_field, "blank", True):
            widget = CHAR_FIELD.widget_factory(context)
            self.assertEqual(list(widget.choices)[0], ("", "---------"))
            self.assertIn('value=""', widget.render("status", ""))
            self.assertEqual(model_field.formfield().clean(""), "")

        # 3. Preserve an explicitly declared empty choice without adding a duplicate.
        source.meta = {"choices": [("", "No status"), *model_field.choices]}
        with patch.object(model_field, "blank", True):
            widget = CHAR_FIELD.widget_factory(
                FieldContext(application_field=source, attrs=source.meta)
            )
            empty_choices = [
                (value, label) for value, label in widget.choices if str(value) == ""
            ]
            self.assertEqual(empty_choices, [("", "No status")])
