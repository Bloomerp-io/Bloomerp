"""Query formats normalize to readable, typed filter definitions."""
from django.core.exceptions import ValidationError
from django.http import QueryDict

from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.filters.parser import deserialize_filters, parse_filters
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels


class TestFilterParser(BaseBloomerpTestCaseWithModels):
    create_foreign_models = True
    auto_create_customers = False

    def parse(self, args):
        return parse_filters(args, model=self.CustomerModel)

    def condition(self, path, value, lookup="equals"):
        return FilterCondition(field_path=path, lookup_id=lookup, value=value)

    def test_empty_and_control_parameters(self):
        """
        UC: Parse empty input, control parameters only, or filter=[].

        Expected Result: No filter groups are returned.
        """
        self.assertEqual(self.parse({}), [])
        self.assertEqual(self.parse({"page": "2", "ordering": "first_name"}), [])
        self.assertEqual(self.parse({"filter": "[]"}), [])

    def test_bare_field_and_registered_aliases(self):
        """
        UC: Filter first_name=David using a bare field or a registered equality alias.

        Expected Result: Each spelling produces one AND group with the canonical equals lookup.
        """
        for key in ("first_name", "first_name_eq", "first_name__exact", "first_name_equals"):
            with self.subTest(key=key):
                self.assertEqual(self.parse({key: "David"}), [Filter(
                    connector="AND", conditions=[self.condition("first_name", "David")],
                )])

    def test_nested_field_and_comparison(self):
        """
        UC: Parse country__name_eq=Belgium and age__gte=18 together.

        Expected Result: One AND group contains the nested equality and greater_than_or_equal conditions; values remain strings.
        """
        self.assertEqual(self.parse({"country__name_eq": "Belgium", "age__gte": "18"}), [Filter(
            connector="AND", conditions=[
                self.condition("country__name", "Belgium"),
                self.condition("age", "18", "greater_than_or_equal"),
            ],
        )])

    def test_repeated_values_are_separate_and_conditions(self):
        """
        UC: Parse age_gt=18&age_gt=21 from a QueryDict.

        Expected Result: Both values become separate greater_than conditions in one AND group.
        """
        self.assertEqual(self.parse(QueryDict("age_gt=18&age_gt=21")), [Filter(
            connector="AND", conditions=[
                self.condition("age", "18", "greater_than"),
                self.condition("age", "21", "greater_than"),
            ],
        )])

    def test_mapping_list_is_one_lookup_value(self):
        """
        UC: Parse a dictionary containing age_in=[18, 21].

        Expected Result: One values_in condition retains the complete list of integers.
        """
        group = self.parse({"age_in": [18, 21]})[0]
        self.assertEqual(group.conditions, [self.condition("age", [18, 21], "values_in")])

    def test_json_and_shorthand_preserve_groups_and_types(self):
        """
        UC: Combine a JSON OR group for ages 18 and 21 with first_name=David shorthand.

        Expected Result: The OR group retains its integer values and is followed by a separate AND group for first_name.
        """
        group = Filter(connector="OR", conditions=[self.condition("age", 18), self.condition("age", 21)])
        self.assertEqual(self.parse({"filter": f"[{group.model_dump_json()}]", "first_name": "David"}), [
            group, Filter(connector="AND", conditions=[self.condition("first_name", "David")]),
        ])

    def test_repeated_json_parameters_preserve_every_group(self):
        """
        UC: Supply two filter parameters containing an empty AND group and an empty OR group.

        Expected Result: Both groups are returned in their original order with their connectors preserved.
        """
        args = QueryDict(mutable=True)
        args.setlist("filter", ['[{"connector":"AND"}]', '[{"connector":"OR"}]'])
        self.assertEqual(self.parse(args), [Filter(connector="AND"), Filter(connector="OR")])

    def test_invalid_json_is_never_an_empty_filter(self):
        """
        UC: Supply blank, malformed, non-string, or structurally invalid filter JSON.

        Expected Result: Every invalid input raises ValidationError rather than returning no filters.
        """
        for value in ("", "null", "{}", "broken", '[{"connector":"X"}]',
                      '[{"connector":"AND","conditions":[{"field_path":"age"}]}]', []):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                deserialize_filters(value)

    def test_unknown_fields_and_unsupported_lookups_fail(self):
        """
        UC: Filter an unknown field, an unknown nested field, or an unsupported lookup.

        Expected Result: Every invalid parameter raises ValidationError.
        """
        for key in ("missing", "age_unknown", "country__missing_eq", "first_name_foreign_advanced"):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                self.parse({key: "value"})
