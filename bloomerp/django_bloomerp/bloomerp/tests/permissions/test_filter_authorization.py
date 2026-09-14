"""Filter references may only depend on data the user is allowed to inspect."""
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError

from bloomerp.filters.definition import Filter, FilterCondition
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
