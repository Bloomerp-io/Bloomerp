"""Filter references may only depend on data the user is allowed to inspect."""
import json
from functools import partial
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from bloomerp.filters.definition import Filter, FilterCondition, Filters
from bloomerp.filters.manager import ModelFilterManager
from bloomerp.filters.resolver import FilterFieldResolver
from bloomerp.permissions.definition import BloomerpPermission, RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager, UserPolicyManager
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels


class TestFilterAuthorization(BaseBloomerpTestCaseWithModels):
    create_foreign_models = True

    def grant(self, model, fields, *, conditions=None):
        policy = PolicyManager.create_policy(
            model_or_content_type=model,
            global_permissions=[BloomerpPermission.VIEW],
            field_permissions={field: [BloomerpPermission.VIEW] for field in fields},
            row_permissions=[RowPolicyRuleContent(
                connector="AND", conditions=conditions or [], permissions=[BloomerpPermission.VIEW],
            )],
        )
        PolicyManager.assign(policy, self.normal_user)

    @staticmethod
    def filters(path, lookup="equals", value="Belgium"):
        return [Filter(connector="AND", conditions=[
            FilterCondition(field_path=path, lookup_id=lookup, value=value),
        ])]

    def test_root_field_is_allowed_and_validation_does_not_mutate_filters(self):
        self.grant(self.CustomerModel, ["first_name"], conditions=[
            FilterCondition(field_path="age", lookup_id="greater_than", value=20),
        ])
        filters = self.filters("first_name", value="David")
        before = [group.model_dump() for group in filters]
        self.assertIsNone(UserPolicyManager(self.normal_user).validate_filters(self.CustomerModel, filters))
        self.assertEqual([group.model_dump() for group in filters], before)

    def test_anonymous_and_no_model_access_are_denied(self):
        for user in (AnonymousUser(), self.normal_user):
            with self.subTest(user=str(user)), self.assertRaises(PermissionDenied):
                UserPolicyManager(user).validate_filters(self.CustomerModel, self.filters("first_name"))

    def test_or_does_not_hide_a_forbidden_condition(self):
        self.grant(self.CustomerModel, ["first_name"])
        filters = [Filter(connector="OR", conditions=[
            FilterCondition(field_path="first_name", lookup_id="equals", value="David"),
            FilterCondition(field_path="age", lookup_id="equals", value=25),
        ])]
        with self.assertRaises(PermissionDenied):
            UserPolicyManager(self.normal_user).validate_filters(self.CustomerModel, filters)

    def test_related_model_without_access_is_denied(self):
        self.grant(self.CustomerModel, ["country"])
        with self.assertRaises(PermissionDenied):
            UserPolicyManager(self.normal_user).validate_filters(self.CustomerModel, self.filters("country__name"))

    def test_related_row_restrictions_are_rejected_even_without_an_aggregate(self):
        self.grant(self.CustomerModel, ["country"])
        self.grant(self.CountryModel, ["name"], conditions=[
            FilterCondition(field_path="name", lookup_id="equals", value="Belgium"),
        ])
        with self.assertRaisesMessage(PermissionDenied, "Related-row filtering"):
            UserPolicyManager(self.normal_user).validate_filters(self.CustomerModel, self.filters("country__name"))

    def test_unconditional_related_access_allows_traversal(self):
        self.grant(self.CustomerModel, ["country"])
        self.grant(self.CountryModel, ["name"])
        self.assertIsNone(UserPolicyManager(self.normal_user).validate_filters(self.CustomerModel, self.filters("country__name")))

    def test_related_field_denied_despite_all_rows_access(self):
        self.grant(self.CustomerModel, ["country"])
        self.grant(self.CountryModel, ["planet"])
        with self.assertRaises(PermissionDenied):
            UserPolicyManager(self.normal_user).validate_filters(self.CustomerModel, self.filters("country__name"))

    def test_every_relation_in_a_deep_path_is_checked(self):
        self.grant(self.CustomerModel, ["country"])
        self.grant(self.CountryModel, ["planet"])
        filters = self.filters("country__planet__name", value="Earth")
        with self.assertRaises(PermissionDenied):
            UserPolicyManager(self.normal_user).validate_filters(self.CustomerModel, filters)
        self.grant(self.PlanetModel, ["name"])
        self.assertIsNone(UserPolicyManager(self.normal_user).validate_filters(self.CustomerModel, filters))
        dependencies = FilterFieldResolver.for_model(self.CustomerModel).resolve_dependencies("country__planet__name")
        self.assertEqual([field.field for field in dependencies], ["country", "country__planet", "country__planet__name"])

    def test_count_references_related_rows_without_a_child_field_segment(self):
        self.grant(self.CountryModel, ["customers"])
        self.grant(self.CustomerModel, ["first_name"], conditions=[
            FilterCondition(field_path="age", lookup_id="greater_than", value=20),
        ])
        filters = self.filters("customers", lookup="count_greater_than", value=1)
        with self.assertRaisesMessage(PermissionDenied, "Related-row filtering"):
            UserPolicyManager(self.normal_user).validate_filters(self.CountryModel, filters)
        self.assertIsNone(UserPolicyManager(self.admin_user).validate_filters(self.CountryModel, filters))

    def test_field_grants_for_some_root_rows_are_not_enough(self):
        self.grant(self.CustomerModel, ["first_name"], conditions=[
            FilterCondition(field_path="age", lookup_id="less_than", value=25),
        ])
        self.grant(self.CustomerModel, ["last_name"], conditions=[
            FilterCondition(field_path="age", lookup_id="greater_than", value=24),
        ])
        with self.assertRaises(PermissionDenied):
            UserPolicyManager(self.normal_user).validate_filters(self.CustomerModel, self.filters("first_name"))
        self.grant(self.CustomerModel, ["first_name"])
        self.assertIsNone(UserPolicyManager(self.normal_user).validate_filters(self.CustomerModel, self.filters("first_name")))

    def test_boolean_wrapper_does_not_swallow_invalid_paths(self):
        self.grant(self.CustomerModel, ["first_name"])
        manager = UserPolicyManager(self.normal_user)
        self.assertTrue(manager.can_execute_filters(self.CustomerModel, self.filters("first_name")))
        self.assertFalse(manager.can_execute_filters(self.CustomerModel, self.filters("age")))
        with self.assertRaises(ValidationError):
            manager.can_execute_filters(self.CustomerModel, self.filters("missing_field"))


    def test_manager_recovery_validates_each_condition_before_cleaning(self) -> None:
        """Forbidden known fields never reach compilation or value cleaning, regardless of lookup."""
        self.grant(self.CustomerModel, ["first_name"])
        manager = ModelFilterManager(self.CustomerModel)
        validate = partial(UserPolicyManager(self.normal_user).validate_filters, self.CustomerModel)
        for lookup in ("equals", "not_registered", "contains"):
            with self.subTest(lookup=lookup):
                args = {"filter": json.dumps([{
                    "connector": "OR", "conditions": [
                        {"field_path": "age", "lookup_id": lookup, "value": "invalid"},
                    ],
                }])}
                with patch("bloomerp.filters.manager.compile_condition") as compile_condition, patch(
                    "bloomerp.filters.compiler.clean_lookup_value",
                ) as clean_value:
                    self.assertEqual(manager.parse(args, recover=True, validate_filters=validate), [])
                    compile_condition.assert_not_called()
                    clean_value.assert_not_called()
                    with self.assertRaises(PermissionDenied):
                        manager.filter(args, self.CustomerModel.objects.all(), validate_filters=validate)
                    compile_condition.assert_not_called()
                    clean_value.assert_not_called()

    def test_manager_recovery_drops_unknown_paths_before_compilation(self) -> None:
        """An authorization callback's invalid path error is recovered before compiler execution."""
        self.grant(self.CustomerModel, ["first_name"])
        args = {"filter": json.dumps([{
            "connector": "AND", "conditions": [
                {"field_path": "missing_field", "lookup_id": "equals", "value": "value"},
            ],
        }])}
        validate = partial(UserPolicyManager(self.normal_user).validate_filters, self.CustomerModel)
        with patch("bloomerp.filters.manager.compile_condition") as compile_condition, patch(
            "bloomerp.filters.compiler.clean_lookup_value",
        ) as clean_value:
            self.assertEqual(ModelFilterManager(self.CustomerModel).parse(args, recover=True, validate_filters=validate), [])
            compile_condition.assert_not_called()
            clean_value.assert_not_called()

    def test_manager_recovery_preserves_allowed_or_siblings_of_nested_denials(self) -> None:
        """Recover nested permission failures independently while retaining the parent's OR connector."""
        self.grant(self.CustomerModel, ["first_name", "country"])
        self.grant(self.CountryModel, ["name", "planet"])
        allowed = self.CustomerModel.objects.first()
        condition = FilterCondition(field_path="first_name", lookup_id="equals", value=allowed.first_name)
        args = {"filter": json.dumps([{
            "connector": "OR", "conditions": [
                condition.model_dump(),
                {"field_path": "country__planet__name", "lookup_id": "equals", "value": "Earth"},
            ],
        }])}
        validate = partial(UserPolicyManager(self.normal_user).validate_filters, self.CustomerModel)
        manager = ModelFilterManager(self.CustomerModel)
        groups = manager.parse(args, recover=True, validate_filters=validate)
        self.assertEqual(groups, [Filter(connector="OR", conditions=[condition])])
        result = manager.filter(args, self.CustomerModel.objects.all(), recover=True, validate_filters=validate)
        self.assertEqual(set(result.values_list("pk", flat=True)), {allowed.pk})
        with self.assertRaises(PermissionDenied):
            manager.filter(args, self.CustomerModel.objects.all(), validate_filters=validate)

    def test_manager_recovery_denied_relation_does_not_query_related_data(self) -> None:
        """Authorize relation dependencies before model-choice cleaning can query related rows."""
        self.grant(self.CustomerModel, ["first_name"])
        country_id = self.CountryModel.objects.first().pk
        validate = partial(UserPolicyManager(self.normal_user).validate_filters, self.CustomerModel)
        manager = ModelFilterManager(self.CustomerModel)
        with CaptureQueriesContext(connection) as queries, patch(
            "bloomerp.filters.compiler.clean_lookup_value",
        ) as clean_value:
            self.assertEqual(manager.parse({"country": str(country_id)}, recover=True, validate_filters=validate), [])
            clean_value.assert_not_called()
        table = connection.ops.quote_name(self.CountryModel._meta.db_table)
        self.assertFalse(any(f"FROM {table}" in query["sql"] for query in queries.captured_queries))

    def test_manager_recovery_allows_authorized_relation_and_preserves_row_scope(self) -> None:
        """Authorized relation filters work without replacing the caller's row-restricted queryset."""
        self.grant(self.CustomerModel, ["country"])
        self.grant(self.CountryModel, ["name"])
        country = self.CountryModel.objects.first()
        entries = list(self.CustomerModel.objects.order_by("pk")[:2])
        for entry in entries:
            entry.country = country
            entry.save()
        restricted = self.CustomerModel.objects.filter(pk=entries[0].pk)
        validate = partial(UserPolicyManager(self.normal_user).validate_filters, self.CustomerModel)
        manager = ModelFilterManager(self.CustomerModel)
        args = {"country__name": country.name, "missing_field": "ignored"}
        result = manager.filter(args, restricted, recover=True, validate_filters=validate)
        self.assertEqual(set(result.values_list("pk", flat=True)), {entries[0].pk})

    def test_manager_callback_receives_single_conditions_with_original_values(self) -> None:
        """Run dependency authorization on each condition without mutating its group or raw value."""
        self.grant(self.CustomerModel, ["first_name", "age"])
        policy_manager = UserPolicyManager(self.normal_user)
        received: list[Filters] = []

        def validate(groups: Filters) -> None:
            """Record the callback contract and delegate real dependency authorization."""
            self.assertEqual(len(groups), 1)
            self.assertEqual(len(groups[0].conditions), 1)
            received.append(groups)
            policy_manager.validate_filters(self.CustomerModel, groups)

        conditions = [
            FilterCondition(field_path="age", lookup_id="equals", value="25"),
            FilterCondition(field_path="first_name", lookup_id="equals", value="David"),
        ]
        original = Filter(connector="OR", conditions=conditions)
        args = {"filter": f"[{original.model_dump_json()}]"}
        groups = ModelFilterManager(self.CustomerModel).parse(args, recover=True, validate_filters=validate)
        self.assertEqual(groups, [original])
        self.assertEqual([group[0].conditions[0] for group in received], conditions)
        self.assertEqual(conditions[0].value, "25")
