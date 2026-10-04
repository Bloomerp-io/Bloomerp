"""Check metadata defaults and overrides in display-option factories."""

from django import forms
from django.test import SimpleTestCase
from bloomerp.field_types.display_options import FieldDisplayOption
from bloomerp.models import ApplicationField
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
            field_type="CharField", meta={"choices": [["completed", "Completed"]]}
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
