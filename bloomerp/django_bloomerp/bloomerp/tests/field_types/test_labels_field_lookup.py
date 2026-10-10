"""Exercise label membership across real ORM, SQL, and Python filter execution."""

from typing import Any

from django.contrib.contenttypes.models import ContentType

from bloomerp.field_types.builtins.labels import LABELS_FIELD
from bloomerp.filters.compiler import compile_condition, compile_sql_filters
from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.lookups.definition import FilterFieldContext
from bloomerp.models import ApplicationField, Label, ObjectLabel, Todo
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels


class TestLabelsFieldLookup(BaseBloomerpTestCaseWithModels):
    """Verify membership is model-scoped, duplicate-free, and composable."""

    auto_create_customers = False

    def extendedSetup(self) -> None:
        """Seed unlabeled, singly labeled, shared, and same-ID foreign-model records."""
        self.empty = self.create_customer("Empty", "Labels", 30)
        self.one = self.create_customer("One", "Label", 30)
        self.both = self.create_customer("Both", "Labels", 30)
        self.red = Label.objects.create(name="Red")
        self.blue = Label.objects.create(name="Blue")
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        for obj, label in [
            (self.one, self.red),
            (self.both, self.red),
            (self.both, self.blue),
        ]:
            ObjectLabel.objects.create(
                content_type=content_type, object_id=str(obj.pk), label=label
            )
        other = Todo.objects.create(pk=self.empty.pk, title="Different model")
        ObjectLabel.objects.create(
            content_type=ContentType.objects.get_for_model(other),
            object_id=str(other.pk),
            label=self.blue,
        )

    def test_membership_matches_in_orm_sql_and_python(self) -> None:
        """Run shared filters against actual rows to prove SQL and collection semantics."""
        cases: list[tuple[str, Any, list[Any]]] = [
            ("equals", self.red.pk, [self.one, self.both]),
            ("equals", self.blue.pk, [self.both]),
            ("not_equals", self.red.pk, [self.empty]),
            ("values_in", [self.red.pk, self.blue.pk], [self.one, self.both]),
            ("values_in", [], []),
            ("is_null", True, [self.empty]),
            ("is_null", False, [self.one, self.both]),
        ]
        for lookup_id, value, expected in cases:
            with self.subTest(lookup=lookup_id, value=value):
                condition = FilterCondition(
                    field_path="object_labels", lookup_id=lookup_id, value=value
                )
                compiled = compile_condition(condition, model=self.CustomerModel)
                self.assertCountEqual(
                    list(self.CustomerModel.objects.filter(compiled.predicate)),
                    expected,
                )
                sql = compile_sql_filters(
                    [Filter(connector="AND", conditions=[condition])],
                    model=self.CustomerModel,
                )
                self.assertCountEqual(
                    list(
                        self.CustomerModel.objects.raw(
                            f'SELECT * FROM "{self.CustomerModel._meta.db_table}" WHERE {sql.clause}',
                            sql.parameters,
                        )
                    ),
                    expected,
                )
                lookup = next(
                    item for item in LABELS_FIELD.lookups if item.id == lookup_id
                )
                self.assertCountEqual(
                    [
                        obj
                        for obj in [self.empty, self.one, self.both]
                        if lookup.get_python_evaluator()(obj.object_labels, value)
                    ],
                    expected,
                )

    def test_discovery_and_label_choices(self) -> None:
        """Expose Labels and label names to the ordinary filter-value editor."""
        field = ApplicationField.get_by_field(self.CustomerModel, "object_labels")
        self.assertEqual(field.get_field_type().id, "BloomerpLabelsField")
        self.assertFalse(self.CustomerModel._meta.get_field("object_labels").concrete)
        context = FilterFieldContext(application_field=field, field_type=LABELS_FIELD)
        self.assertEqual(
            LABELS_FIELD.lookups[0].get_form_factory()(context).clean(str(self.red.pk)),
            self.red,
        )
        self.assertCountEqual(
            LABELS_FIELD.lookups[2]
            .get_form_factory()(context)
            .clean([str(self.red.pk), str(self.blue.pk)]),
            [self.red, self.blue],
        )
        self.assertEqual(self.CustomerModel().object_labels, [])
        self.assertFalse(Todo._meta.get_field("object_labels").concrete)
        self.assertTrue(Todo._meta.get_field("labels").many_to_many)

    def test_label_conditions_compose_as_all_selected(self) -> None:
        """Two AND conditions can require both labels on the same parent record."""
        predicates = [
            compile_condition(
                FilterCondition(
                    field_path="object_labels", lookup_id="equals", value=label.pk
                ),
                model=self.CustomerModel,
            ).predicate
            for label in [self.red, self.blue]
        ]
        self.assertEqual(
            list(self.CustomerModel.objects.filter(predicates[0] & predicates[1])),
            [self.both],
        )
