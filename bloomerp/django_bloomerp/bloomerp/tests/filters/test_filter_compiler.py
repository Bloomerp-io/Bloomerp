"""The same predicates must select the same rows through Q, SQL and permissions."""
from django.core.exceptions import ValidationError
from django.db import connection
from pydantic import ValidationError as PydanticValidationError

from bloomerp.filters.compiler import compile_filters, compile_sql_filters, resolve_condition
from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.filters.manager import ModelFilterManager
from bloomerp.permissions.compilers.django_q_permission_compiler import DjangoQPermissionCompiler
from bloomerp.permissions.compilers.python_permission_compiler import PythonPermissionCompiler
from bloomerp.permissions.definition import AccessRule, RowPolicyRuleContent
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels


class TestSharedFilterCompiler(BaseBloomerpTestCaseWithModels):
    create_foreign_models = True
    auto_create_customers = False

    def extendedSetup(self):
        country = self.CountryModel.objects.first()
        self.entries = [
            self.CustomerModel.objects.create(first_name=f"Person {age}", last_name="Example", age=age, country=country if age else None)
            for age in (0, 2, 4, 6)
        ]

    def assert_backends_match(self, groups, ages):
        model = self.CustomerModel
        expected = {entry.pk for entry in self.entries if entry.age in ages}
        queryset = ModelFilterManager(model).apply(groups, model.objects.all())
        self.assertEqual(set(queryset.values_list("pk", flat=True)), expected)
        compiled = compile_sql_filters(groups, model=model)
        quote = connection.ops.quote_name
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {quote(model._meta.pk.column)} FROM {quote(model._meta.db_table)} WHERE {compiled.clause}",
                compiled.parameters,
            )
            self.assertEqual({model._meta.pk.to_python(row[0]) for row in cursor.fetchall()}, expected)

    def test_equality_and_numeric_coercion(self):
        condition = FilterCondition(field_path="age", lookup_id="equals", value="2")
        self.assertIs(type(resolve_condition(condition, model=self.CustomerModel)[3]), int)
        self.assert_backends_match([Filter(connector="AND", conditions=[condition])], {2})

    def test_group_connectors_and_implicit_outer_and(self):
        alternatives = Filter(connector="OR", conditions=[
            FilterCondition(field_path="age", lookup_id="equals", value=0),
            FilterCondition(field_path="age", lookup_id="greater_than", value=3),
        ])
        self.assert_backends_match([alternatives], {0, 4, 6})
        upper_bound = Filter(connector="AND", conditions=[
            FilterCondition(field_path="age", lookup_id="less_than", value=6),
        ])
        self.assert_backends_match([alternatives, upper_bound], {0, 4})

    def test_nested_relation_and_nullable_relation_in_or(self):
        nested = FilterCondition(field_path="country__name", lookup_id="equals", value=self.entries[1].country.name)
        self.assert_backends_match([Filter(connector="AND", conditions=[nested])], {2, 4, 6})
        self.assert_backends_match([Filter(connector="OR", conditions=[
            nested, FilterCondition(field_path="age", lookup_id="equals", value=0),
        ])], {0, 2, 4, 6})

    def test_sql_values_stay_parameters(self):
        value = "Robert'); DROP TABLE customer; --"
        groups = [Filter(connector="AND", conditions=[
            FilterCondition(field_path="first_name", lookup_id="equals", value=value),
        ])]
        compiled = compile_sql_filters(groups, model=self.CustomerModel)
        self.assertNotIn(value, compiled.clause)
        self.assertIn(value, compiled.parameters)
        self.assert_backends_match(groups, set())

    def test_shared_filter_is_a_row_policy(self):
        group = Filter(connector="AND", conditions=[
            FilterCondition(field_path="age", lookup_id="greater_than", value="2"),
            FilterCondition(field_path="age", lookup_id="less_than", value=6),
        ])
        row_rule = RowPolicyRuleContent(**group.model_dump(), permissions=["view"])
        self.assertIsInstance(row_rule, Filter)
        self.assertTrue(all(isinstance(item, FilterCondition) for item in row_rule.conditions))
        rules = [AccessRule(row_permissions=[row_rule], field_permissions={"__all__": ["view"]})]
        access = DjangoQPermissionCompiler(rules, model=self.CustomerModel).compile("view")
        expected = {self.entries[2].pk}
        self.assertEqual(set(self.CustomerModel.objects.filter(access.row_filter).values_list("pk", flat=True)), expected)
        python = PythonPermissionCompiler(rules, model=self.CustomerModel).compile("view")
        self.assertEqual({entry.pk for entry in self.entries if python.matches(entry)}, expected)
        self.assert_backends_match([group], {4})

    def test_invalid_conditions_cannot_turn_or_into_a_grant(self):
        group = Filter(connector="OR", conditions=[
            FilterCondition(field_path="age", lookup_id="equals", value=2),
            FilterCondition(field_path="age", lookup_id="equals", value="invalid"),
        ])
        for compiler in (compile_filters, compile_sql_filters):
            with self.assertRaises(ValidationError):
                compiler([group], model=self.CustomerModel)
        rule = RowPolicyRuleContent(**group.model_dump(), permissions=["view"])
        access = DjangoQPermissionCompiler([AccessRule(row_permissions=[rule])], model=self.CustomerModel).compile("view")
        self.assertFalse(self.CustomerModel.objects.filter(access.row_filter).exists())

    def test_empty_filters_are_not_unconditional_grants(self):
        for compiler in (compile_filters, compile_sql_filters):
            with self.assertRaises(ValidationError):
                compiler([], model=self.CustomerModel)
        access = DjangoQPermissionCompiler([], model=self.CustomerModel).compile("view")
        self.assertFalse(self.CustomerModel.objects.filter(access.row_filter).exists())
        queryset = self.CustomerModel.objects.filter(age=2)
        self.assertIs(ModelFilterManager(self.CustomerModel).apply([], queryset), queryset)

    def test_legacy_policy_is_normalized_and_serializes_shared_conditions(self):
        rule = RowPolicyRuleContent.model_validate({
            "conditions": [{"field": "age", "operator": "gte", "value": 4}],
            "permissions": ["view"],
        })
        self.assertEqual(rule.conditions[0], FilterCondition(field_path="age", lookup_id="greater_than_or_equal", value=4))
        self.assertEqual(set(rule.model_dump()["conditions"][0]), {"field_path", "lookup_id", "value"})
        unconditional = RowPolicyRuleContent.model_validate({"conditions": [{"field": "__all__"}], "permissions": ["view"]})
        self.assertEqual(unconditional.connector, "AND")
        self.assertNotIn("match_all", unconditional.model_dump())
        self.assertEqual(unconditional.conditions, [])

    def test_relation_equality_preserves_primary_key_type(self):
        condition = FilterCondition(field_path="country", lookup_id="equals", value=str(self.entries[1].country_id))
        self.assert_backends_match([Filter(connector="AND", conditions=[condition])], {2, 4, 6})

    def test_list_values_are_cleaned_item_by_item(self):
        condition = FilterCondition(field_path="age", lookup_id="values_in", value=[2, "4"])
        self.assertEqual(resolve_condition(condition, model=self.CustomerModel)[3], [2, 4])
        self.assert_backends_match([Filter(connector="AND", conditions=[condition])], {2, 4})

    def test_legacy_cross_model_reference_cannot_grant_access(self):
        from bloomerp.models.application_field import ApplicationField
        other_field = ApplicationField.get_for_model(self.CountryModel).get(field="name")
        rule = RowPolicyRuleContent.model_validate({
            "conditions": [{"application_field_id": other_field.pk, "operator": "equals", "value": "Belgium"}],
            "permissions": ["view"],
        })
        access = DjangoQPermissionCompiler([AccessRule(row_permissions=[rule])], model=self.CustomerModel).compile("view")
        self.assertFalse(self.CustomerModel.objects.filter(access.row_filter).exists())

    def test_nested_not_equals_includes_missing_relations(self):
        condition = FilterCondition(field_path="country__name", lookup_id="not_equals", value=self.entries[1].country.name)
        self.assert_backends_match([Filter(connector="AND", conditions=[condition])], {0})

    def test_existing_editor_round_trips_shared_nested_rules(self):
        from bloomerp.permissions.legacy import editor_rule
        condition = FilterCondition(field_path="country__name", lookup_id="equals", value="Belgium")
        rule = RowPolicyRuleContent(conditions=[condition])
        restored = RowPolicyRuleContent.model_validate(editor_rule(rule.model_dump(), self.CustomerModel))
        self.assertEqual(restored.conditions, [condition])
        all_rows = RowPolicyRuleContent(connector="AND", conditions=[])
        restored_all = RowPolicyRuleContent.model_validate(editor_rule(all_rows.model_dump(), self.CustomerModel))
        self.assertEqual(restored_all.connector, "AND")
        self.assertEqual(restored_all.conditions, [])

    def test_serializer_checks_legacy_scope_before_discarding_field_ids(self):
        from bloomerp.models.application_field import ApplicationField
        from bloomerp.serializers.access_control import PolicySerializer
        other_field = ApplicationField.get_for_model(self.CountryModel).get(field="name")
        payload = {
            "name": "Example", "description": "",
            "content_type_id": self.get_content_type_for_model(self.CustomerModel).pk,
            "global_permissions": [],
            "field_policy": {"name": "Fields", "rules": {}},
            "row_policy": {"name": "Rows", "rules": [{
                "permissions": [], "rule": {"conditions": [{
                    "application_field_id": other_field.pk, "operator": "equals", "value": "Belgium",
                }]},
            }]},
        }
        serializer = PolicySerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn("different content type", str(serializer.errors))
        payload["row_policy"]["rules"][0]["rule"] = {
            "conditions": [FilterCondition(field_path="age", lookup_id="equals", value=2).model_dump()],
        }
        serializer = PolicySerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        stored = serializer.validated_data["row_policy"]["rules"][0]["rule"]
        self.assertEqual(stored["conditions"][0]["field_path"], "age")

    def test_empty_groups_share_semantics_across_all_backends(self):
        for connector, ages in [("AND", {0, 2, 4, 6}), ("OR", set())]:
            with self.subTest(connector=connector):
                group = Filter(connector=connector, conditions=[])
                self.assert_backends_match([group], ages)
                rule = RowPolicyRuleContent(**group.model_dump(), permissions=["view"])
                self.assertNotIn("match_all", rule.model_dump())
                rules = [AccessRule(row_permissions=[rule])]
                django = DjangoQPermissionCompiler(rules, model=self.CustomerModel).compile("view")
                self.assertEqual(set(self.CustomerModel.objects.filter(django.row_filter).values_list("age", flat=True)), ages)
                python = PythonPermissionCompiler(rules, model=self.CustomerModel).compile("view")
                self.assertEqual({entry.age for entry in self.entries if python.matches(entry)}, ages)

    def test_empty_groups_combine_without_dropping_other_conditions(self):
        matching = Filter(connector="AND", conditions=[
            FilterCondition(field_path="age", lookup_id="equals", value=2),
        ])
        self.assert_backends_match([Filter(connector="AND", conditions=[]), matching], {2})
        self.assert_backends_match([Filter(connector="OR", conditions=[]), matching], set())
        invalid = Filter(connector="AND", conditions=[
            FilterCondition(field_path="age", lookup_id="equals", value="invalid"),
        ])
        for compiler in (compile_filters, compile_sql_filters):
            with self.assertRaises(ValidationError):
                compiler([Filter(connector="AND", conditions=[]), invalid], model=self.CustomerModel, connector="OR")

    def test_all_sentinel_is_only_accepted_as_legacy_input(self):
        for connector in ("AND", "OR"):
            rule = RowPolicyRuleContent.model_validate({"connector": connector, "conditions": [{"field": "__all__"}]})
            self.assertEqual((rule.connector, rule.conditions), ("AND", []))
        condition = FilterCondition(field_path="__all__", lookup_id="equals", value=True)
        with self.assertRaises(ValidationError):
            resolve_condition(condition, model=self.CustomerModel)
        with self.assertRaises(PydanticValidationError):
            RowPolicyRuleContent.model_validate({"connector": "OR", "conditions": [
                {"field": "__all__"},
                {"field_path": "age", "lookup_id": "equals", "value": "invalid"},
            ]})
