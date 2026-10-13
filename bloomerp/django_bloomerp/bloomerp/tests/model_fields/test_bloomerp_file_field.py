from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError

from bloomerp.form_fields.bloomerp_file_field import BloomerpFileFormField
from bloomerp.model_fields.file_field import BloomerpFileField
from bloomerp.tests.base import (
    BloomerpModelFieldTestCase,
    ExpectedModelFieldException,
    ModelFieldScenario,
)


class TestBloomerpFileField(BloomerpModelFieldTestCase[BloomerpFileField]):
    field_class = BloomerpFileField
    attachment_id = "12345678-1234-5678-1234-567812345678"

    def get_test_scenarios(self) -> list[ModelFieldScenario[BloomerpFileField]]:
        """Cover virtual attachment values, construction options, and form selection."""
        return [
            ModelFieldScenario(
                name="defaults to optional single attachment",
                construct_validators=self.default_options,
            ),
            ModelFieldScenario(
                name="preserves multiple upload construction options",
                constructor_kwargs={
                    "multiple": True,
                    "allowed_extensions": [".pdf"],
                    "max_files": 3,
                    "max_file_size": 1024,
                },
                deconstruct_validators=self.options_survive_migrations,
            ),
            ModelFieldScenario(
                name="normalizes historical single ID",
                to_python_value=UUID(self.attachment_id),
                to_python_validators=self.is_attachment_list,
            ),
            ModelFieldScenario(
                name="deduplicates submitted IDs",
                get_prep_value=[self.attachment_id, self.attachment_id],
                get_prep_value_validators=self.is_attachment_list,
            ),
            ModelFieldScenario(
                name="normalizes empty optional value",
                to_python_value=None,
                to_python_validators=self.is_empty,
            ),
            ModelFieldScenario(
                name="rejects malformed IDs",
                to_python_value="invalid",
                expected_exceptions=[
                    ExpectedModelFieldException(
                        phase="to_python", exception=ValidationError
                    )
                ],
            ),
        ]

    def default_options(self, field: BloomerpFileField) -> bool:
        """Check single-file defaults and the upload form field contract."""
        return (
            not field.multiple
            and field.blank
            and field.allowed_extensions == "__all__"
            and isinstance(field.formfield(), BloomerpFileFormField)
        )

    def options_survive_migrations(
        self, value: tuple[str, str, list[Any], dict[str, Any]]
    ) -> bool:
        """Check reconstructed fields keep configured upload limits."""
        reconstructed = BloomerpFileField(*value[2], **value[3])
        return (
            reconstructed.multiple
            and reconstructed.allowed_extensions == [".pdf"]
            and reconstructed.max_files == 3
            and reconstructed.max_file_size == 1024
        )

    def is_attachment_list(self, value: Any) -> bool:
        """Check normalized submission contains one string UUID."""
        return value == [self.attachment_id]

    def is_empty(self, value: Any) -> bool:
        """Check an absent attachment becomes an empty list."""
        return value == []
