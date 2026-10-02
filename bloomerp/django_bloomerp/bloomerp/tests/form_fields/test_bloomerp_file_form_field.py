from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from bloomerp.form_fields.bloomerp_file_field import (
    BloomerpFileFormField,
    FileFieldCleanedData,
)
from bloomerp.tests.base import (
    BloomerpFormFieldTestCase,
    ExpectedFormFieldException,
    FormFieldScenario,
)


class TestBloomerpFileFormField(BloomerpFormFieldTestCase):
    field_class = BloomerpFileFormField

    def get_test_scenarios(self) -> list[FormFieldScenario]:
        """Cover upload cardinality, required fields, extensions, size, and ID safety."""
        return [
            FormFieldScenario(
                name="accepts one upload without persistence",
                clean_value=SimpleUploadedFile("report.pdf", b"data"),
                clean_result_validators=self.one_upload,
            ),
            FormFieldScenario(
                name="accepts multiple uploads",
                constructor_kwargs={"multiple": True},
                clean_value=[
                    SimpleUploadedFile("a.pdf", b"a"),
                    SimpleUploadedFile("b.pdf", b"b"),
                ],
                clean_result_validators=self.two_uploads,
            ),
            FormFieldScenario(
                name="rejects multiple uploads for single field",
                clean_value=[
                    SimpleUploadedFile("a.pdf", b"a"),
                    SimpleUploadedFile("b.pdf", b"b"),
                ],
                expected_exceptions=[self.validation_error()],
            ),
            FormFieldScenario(
                name="enforces required combined value",
                clean_value=None,
                expected_exceptions=[self.validation_error()],
            ),
            FormFieldScenario(
                name="allows empty optional editor",
                constructor_kwargs={"required": False},
                clean_value=None,
                clean_result_validators=self.empty_uploads,
            ),
            FormFieldScenario(
                name="accepts case-insensitive extension",
                constructor_kwargs={"allowed_extensions": ["pdf"]},
                clean_value=SimpleUploadedFile("a.PDF", b"a"),
                clean_result_validators=self.one_upload,
            ),
            FormFieldScenario(
                name="rejects disallowed extension",
                constructor_kwargs={"allowed_extensions": [".pdf"]},
                clean_value=SimpleUploadedFile("a.exe", b"a"),
                expected_exceptions=[self.validation_error()],
            ),
            FormFieldScenario(
                name="enforces byte size limit",
                constructor_kwargs={"max_file_size": 2},
                clean_value=SimpleUploadedFile("a.pdf", b"abc"),
                expected_exceptions=[self.validation_error()],
            ),
            FormFieldScenario(
                name="enforces maximum file count",
                constructor_kwargs={"multiple": True, "max_files": 1},
                clean_value=[
                    SimpleUploadedFile("a.pdf", b"a"),
                    SimpleUploadedFile("b.pdf", b"b"),
                ],
                expected_exceptions=[self.validation_error()],
            ),
            FormFieldScenario(
                name="rejects unbound retained ID",
                clean_value={"retained": ["12345678-1234-5678-1234-567812345678"]},
                expected_exceptions=[self.validation_error()],
            ),
        ]

    def validation_error(self) -> ExpectedFormFieldException:
        """Declare an expected input validation failure."""
        return ExpectedFormFieldException(phase="clean", exception=ValidationError)

    def one_upload(self, value: FileFieldCleanedData) -> bool:
        """Check one pending upload survives cleaning without creating IDs."""
        return len(value.uploads) == 1 and not value.retained

    def two_uploads(self, value: FileFieldCleanedData) -> bool:
        """Check multiple pending uploads survive cleaning."""
        return len(value.uploads) == 2 and not value.retained

    def empty_uploads(self, value: FileFieldCleanedData) -> bool:
        """Check empty optional values produce an empty structured value."""
        return not value.uploads and not value.retained
