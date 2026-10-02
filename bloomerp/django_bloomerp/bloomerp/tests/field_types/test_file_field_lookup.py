from __future__ import annotations

from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import CharField, Model

from bloomerp.field_types.builtins.other import BLOOMERP_FILE_FIELD
from bloomerp.filters.compiler import compile_condition, compile_sql_filters
from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.lookups.builtins.is_null import IS_NULL
from bloomerp.lookups.definition import FilterFieldContext
from bloomerp.model_fields.file_field import BloomerpFileField
from bloomerp.models import ApplicationField, File
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels
from bloomerp.tests.utils.dynamic_models import create_test_models


class TestFileFieldIsNullLookup(BaseBloomerpTestCaseWithModels):
    auto_create_customers = False

    def matching_objects(self, value: Any, *, field: str = "picture") -> list[Model]:
        """Execute the registered lookup through the shared condition compiler."""
        compiled = compile_condition(
            FilterCondition(field_path=field, lookup_id="is_null", value=value),
            model=self.CustomerModel,
        )
        return list(self.CustomerModel.objects.filter(compiled.predicate))

    def test_empty_and_populated_fields(self) -> None:
        """
        Use case: Objects have empty fields, multiple attachments, or generic uploads.
        Expected result: IS_NULL checks only references owned by the selected file field.
        """
        # 1. Seed both file-field states and an unrelated generic object upload.
        empty = self.create_customer("Empty", "Field", 30)
        generic_owner = self.create_customer("Generic", "Files", 30)
        populated = self.create_customer("Populated", "Field", 30)
        field = self.CustomerModel._meta.get_field("picture")
        field.multiple = True
        field.on_save(
            populated,
            [],
            [
                SimpleUploadedFile("one.pdf", b"one"),
                SimpleUploadedFile("two.pdf", b"two"),
            ],
        )
        File.objects.create(
            file=SimpleUploadedFile("generic.pdf", b"pdf"), content_object=generic_owner
        )
        # 2. True matches empty fields; false matches populated fields exactly once.
        self.assertCountEqual(self.matching_objects(True), [empty, generic_owner])
        self.assertEqual(self.matching_objects(False), [populated])
        # 3. The reused Boolean editor accepts serialized filter values as well.
        self.assertCountEqual(self.matching_objects("true"), [empty, generic_owner])
        self.assertEqual(self.matching_objects("false"), [populated])
        # 4. SQL filtering uses the same adapter because virtual fields have no column.
        for value, expected in [(True, [empty, generic_owner]), (False, [populated])]:
            with self.subTest(sql_value=value):
                compiled_sql = compile_sql_filters(
                    [
                        Filter(
                            connector="AND",
                            conditions=[
                                FilterCondition(
                                    field_path="picture",
                                    lookup_id="is_null",
                                    value=value,
                                )
                            ],
                        )
                    ],
                    model=self.CustomerModel,
                )
                self.assertCountEqual(
                    list(
                        self.CustomerModel.objects.raw(
                            f'SELECT * FROM "{self.CustomerModel._meta.db_table}" WHERE {compiled_sql.clause}',
                            compiled_sql.parameters,
                        )
                    ),
                    expected,
                )

    def test_references_are_scoped_to_the_selected_field(self) -> None:
        """
        Use case: An object has a file in another attachment field.
        Expected result: That reference does not populate the selected field.
        """
        # 1. Add another virtual file field and attach a file exclusively to it.
        self.CustomerModel.add_to_class("documents", BloomerpFileField())
        picture = ApplicationField.get_by_field(self.CustomerModel, "picture")
        ApplicationField.objects.create(
            content_type=picture.content_type,
            field="documents",
            field_type="BloomerpFileField",
        )
        customer = self.create_customer("Other", "Field", 30)
        self.CustomerModel._meta.get_field("documents").on_save(
            customer, [], [SimpleUploadedFile("doc.pdf", b"pdf")]
        )
        # 2. Evaluate each field independently through the same registered operator.
        self.assertEqual(self.matching_objects(True), [customer])
        self.assertEqual(self.matching_objects(False), [])
        self.assertEqual(self.matching_objects(False, field="documents"), [customer])

    def test_existing_lookup_and_editor_are_reused(self) -> None:
        """
        Use case: The filter editor discovers IS_NULL on a Bloomerp file field.
        Expected result: It reuses the existing definition and Boolean value editor.
        """
        # 1. Inspect the bound lookup and build its registered value editor.
        field = ApplicationField.get_by_field(self.CustomerModel, "picture")
        bound_lookup = BLOOMERP_FILE_FIELD.lookups[0]
        self.assertIs(bound_lookup.lookup, IS_NULL)
        self.assertIs(bound_lookup.get_form_factory(), IS_NULL.default_form_factory)
        editor = bound_lookup.get_form_factory()(
            FilterFieldContext(
                application_field=field, field_type=field.get_field_type()
            )
        )
        # 2. In-memory evaluation follows the collection's emptiness, matching the query.
        self.assertTrue(editor.clean(True))
        self.assertFalse(editor.clean(False))
        evaluator = bound_lookup.get_python_evaluator()
        self.assertTrue(evaluator([], True))
        self.assertFalse(evaluator([object()], True))
        self.assertTrue(evaluator([object()], False))
        self.assertFalse(evaluator([], False))

    def test_integer_parent_ids(self) -> None:
        """
        Use case: A file field belongs to a model with an integer primary key.
        Expected result: String reference IDs match the owning integer IDs.
        """
        # 1. Create an independent integer-key model and register its file field.
        model = create_test_models(
            app_label="bloomerp",
            model_defs={
                "FileLookupIntegerOwner": {
                    "name": CharField(max_length=100),
                    "attachments": BloomerpFileField(),
                }
            },
        )["FileLookupIntegerOwner"]
        ApplicationField.objects.create(
            content_type=ContentType.objects.get_for_model(model),
            field="attachments",
            field_type="BloomerpFileField",
        )
        empty = model.objects.create(name="Empty")
        populated = model.objects.create(name="Populated")
        model._meta.get_field("attachments").on_save(
            populated, [], [SimpleUploadedFile("integer.pdf", b"pdf")]
        )
        # 2. Run both states through the shared compiler against real integer owners.
        for value, expected in [(True, [empty]), (False, [populated])]:
            with self.subTest(value=value):
                compiled = compile_condition(
                    FilterCondition(
                        field_path="attachments", lookup_id="is_null", value=value
                    ),
                    model=model,
                )
                self.assertEqual(
                    list(model.objects.filter(compiled.predicate)), expected
                )
