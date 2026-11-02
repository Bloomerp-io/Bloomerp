"""Exercise base-filter query composition independently of model lifecycle."""

from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db.models import Value

from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.models.definition import BloomerpModelConfig, apply_model_base_filter
from bloomerp.permissions.definition import AccessRule, RowPolicyRuleContent
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels


class TestModelBaseFilter(BaseBloomerpTestCaseWithModels):
    """Cover queryset composition that does not fit create/update/delete scenarios."""

    auto_create_customers = False

    def setUp(self) -> None:
        """Create visible and hidden rows and install a temporary base filter."""
        super().setUp()
        self.visible = self.create_customer("Visible", "Customer", 30)
        self.hidden = self.create_customer("Hidden", "Customer", 10)
        self.config = BloomerpModelConfig(
            base_filter=Filter(
                connector="AND",
                conditions=[
                    FilterCondition(
                        field_path="age", lookup_id="greater_than", value=20
                    )
                ],
            )
        )
        self.enterContext(
            patch.object(
                self.CustomerModel, "bloomerp_config", self.config, create=True
            )
        )

    def test_base_filter_preserves_queryset_scope_and_annotations(self) -> None:
        """
        Use case: An embedded view supplies a scoped and annotated queryset.
        Expected result: The base filter narrows it without losing caller state.
        """
        # 1. Prepare an ordered queryset with an annotation and selected database.
        queryset = (
            self.CustomerModel.objects.using("default")
            .annotate(marker=Value("retained"))
            .order_by("first_name")
        )

        # 2. Check the narrowed result and preserved database/annotation/order.
        filtered = apply_model_base_filter(queryset)
        self.assertEqual(filtered.db, queryset.db)
        self.assertEqual(filtered.query.order_by, queryset.query.order_by)
        self.assertEqual(
            list(filtered.values_list("pk", "marker")), [(self.visible.pk, "retained")]
        )
        self.assertFalse(
            apply_model_base_filter(queryset.filter(pk=self.hidden.pk)).exists()
        )

        # 3. Direct ORM access remains available to maintenance/restore code.
        self.assertEqual(self.CustomerModel.objects.count(), 2)

    def test_missing_base_filter_leaves_queryset_unchanged(self) -> None:
        """
        Use case: A model keeps the default optional filter.
        Expected result: Applying it returns the original queryset without work.
        """
        # 1. Reset the optional filter and retain the caller's exact queryset.
        self.config.base_filter = None
        queryset = self.CustomerModel.objects.filter(pk=self.hidden.pk)
        with self.assertNumQueries(0):
            self.assertIs(apply_model_base_filter(queryset), queryset)

    def test_empty_filter_connectors_follow_shared_semantics(self) -> None:
        """
        Use case: A base filter declares an empty AND or OR group.
        Expected result: AND includes all rows and OR includes no rows.
        """
        # 1. Exercise both empty groups through the same filter compiler.
        for connector, expected_count in (("AND", 2), ("OR", 0)):
            with self.subTest(connector=connector):
                self.config.base_filter = Filter(connector=connector)
                self.assertEqual(
                    apply_model_base_filter(self.CustomerModel.objects.all()).count(),
                    expected_count,
                )

    def test_invalid_base_filter_fails_closed(self) -> None:
        """
        Use case: A configured filter references an unknown field.
        Expected result: Query construction raises instead of returning all rows.
        """
        # 1. Install a structurally valid filter with an invalid model field.
        self.config.base_filter.conditions[0].field_path = "unknown_field"

        # 2. Keep configuration errors visible and never widen the queryset.
        with self.assertRaises(ValidationError):
            apply_model_base_filter(self.CustomerModel.objects.all())

    def test_superuser_object_access_respects_base_filter(self) -> None:
        """
        Use case: A superuser reads an object excluded by the model base filter.
        Expected result: Both queryset and object checks exclude that record.
        """
        # 1. Resolve row and object access through the shared policy manager.
        manager = UserPolicyManager(self.admin_user)
        self.assertEqual(
            list(manager.get_queryset(self.CustomerModel, "view")), [self.visible]
        )
        self.assertTrue(manager.has_access_to_object(self.visible, "view"))
        self.assertFalse(manager.has_access_to_object(self.hidden, "view"))

    def test_no_policy_or_anonymous_access_stays_empty(self) -> None:
        """
        Use case: A base filter matches a row but the caller has no row grants.
        Expected result: Matching the base filter never grants access.
        """
        # 1. Check authenticated and anonymous callers without access rules.
        for user in (self.normal_user, AnonymousUser()):
            with self.subTest(user=user):
                self.assertFalse(
                    UserPolicyManager(user)
                    .get_accessible_queryset(self.CustomerModel, "view")
                    .exists()
                )

    def test_explicit_access_rules_intersect_with_base_filter(self) -> None:
        """
        Use case: A draft access rule permits only a base-filtered-out row.
        Expected result: Explicit-rule previews cannot restore excluded records.
        """
        # 1. Grant view access to the hidden record using a shared row predicate.
        rule = AccessRule(
            row_permissions=[
                RowPolicyRuleContent(
                    permissions=["view"],
                    conditions=[
                        FilterCondition(field_path="age", lookup_id="equals", value=10)
                    ],
                )
            ]
        )

        # 2. Intersect supplied rules with the model filter, just like stored rules.
        self.assertFalse(
            UserPolicyManager(self.normal_user)
            .get_queryset_for_access_rules(self.CustomerModel, [rule], "view")
            .exists()
        )
