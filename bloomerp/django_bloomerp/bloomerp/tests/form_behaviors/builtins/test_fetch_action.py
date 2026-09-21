"""Tests for one fetch action across scalar, collection, and per-row targets."""

from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models

from bloomerp.form_behaviors.builtins.fetch import FETCH
from bloomerp.form_behaviors.definition import (
    BehaviorAction,
    BehaviorConfig,
    BehaviorContext,
    BehaviorMessage,
    BehaviorResult,
    FormBehavior,
)
from bloomerp.form_behaviors.execution import BehaviorExecutor
from bloomerp.form_behaviors.utils import clean_action_config
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.users.user_object_layout_preference import (
    UserObjectLayoutPreference,
)
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.tests.base import BloomerpBehaviorActionTestCase
from bloomerp.tests.utils.dynamic_models import create_test_models


class TestFetchAction(BloomerpBehaviorActionTestCase):
    """Verify lookup cardinality, mappings, policies, and draft safety."""

    action = FETCH
    auto_create_customers = False
    invoice_model: type[models.Model]
    work_order_model: type[models.Model]
    work_order_line_model: type[models.Model]
    product_model: type[models.Model]
    rate_model: type[models.Model]

    @classmethod
    def setUpClass(cls) -> None:
        """Create matching source and destination models with shared product relations."""
        super().setUpClass()
        fixtures = create_test_models(
            "bloomerp",
            {
                "UnifiedFetchProduct": {"name": models.CharField(max_length=40)},
                "UnifiedFetchWorkOrder": {"name": models.CharField(max_length=40)},
                "UnifiedFetchWorkOrderLine": {
                    "work_order": models.ForeignKey(
                        "bloomerp.UnifiedFetchWorkOrder",
                        on_delete=models.CASCADE,
                        related_name="lines",
                    ),
                    "product": models.ForeignKey(
                        "bloomerp.UnifiedFetchProduct", on_delete=models.CASCADE
                    ),
                    "quantity": models.IntegerField(),
                    "unit_price": models.DecimalField(max_digits=10, decimal_places=2),
                },
                "UnifiedFetchInvoice": {
                    "name": models.CharField(max_length=40),
                    "work_order": models.ForeignKey(
                        "bloomerp.UnifiedFetchWorkOrder",
                        null=True,
                        blank=True,
                        on_delete=models.SET_NULL,
                    ),
                    "currency": models.CharField(max_length=3),
                    "exchange_rate": models.DecimalField(
                        max_digits=10, decimal_places=4, null=True, blank=True
                    ),
                    "source_rate": models.DecimalField(
                        max_digits=10, decimal_places=4, null=True, blank=True
                    ),
                },
                "UnifiedFetchInvoiceLine": {
                    "invoice": models.ForeignKey(
                        "bloomerp.UnifiedFetchInvoice",
                        on_delete=models.CASCADE,
                        related_name="lines",
                    ),
                    "product": models.ForeignKey(
                        "bloomerp.UnifiedFetchProduct", on_delete=models.CASCADE
                    ),
                    "quantity": models.IntegerField(),
                    "unit_price": models.DecimalField(
                        max_digits=10, decimal_places=2, null=True, blank=True
                    ),
                },
                "UnifiedFetchRate": {
                    "currency": models.CharField(max_length=3),
                    "effective_at": models.DateField(),
                    "rate": models.DecimalField(max_digits=10, decimal_places=4),
                },
            },
            use_bloomerp_base=True,
        )
        cls.product_model = fixtures["UnifiedFetchProduct"]
        cls.work_order_model = fixtures["UnifiedFetchWorkOrder"]
        cls.work_order_line_model = fixtures["UnifiedFetchWorkOrderLine"]
        cls.invoice_model = fixtures["UnifiedFetchInvoice"]
        cls.rate_model = fixtures["UnifiedFetchRate"]

    def setUp(self) -> None:
        """Create source rows whose effective date differs from insertion order."""
        super().setUp()
        self.product_a = self.product_model.objects.create(name="A")
        self.product_b = self.product_model.objects.create(name="B")
        self.work_order = self.work_order_model.objects.create(name="Selected")
        other_order = self.work_order_model.objects.create(name="Other")
        self.work_order_line_model.objects.create(
            work_order=self.work_order,
            product=self.product_a,
            quantity=2,
            unit_price=Decimal("10.25"),
        )
        self.work_order_line_model.objects.create(
            work_order=self.work_order,
            product=self.product_b,
            quantity=3,
            unit_price=Decimal("4.00"),
        )
        self.work_order_line_model.objects.create(
            work_order=other_order,
            product=self.product_a,
            quantity=99,
            unit_price=Decimal("99.00"),
        )
        self.rate_model.objects.create(
            currency="EUR", effective_at=date(2026, 9, 21), rate=Decimal("1.2500")
        )
        self.rate_model.objects.create(
            currency="EUR", effective_at=date(2026, 1, 1), rate=Decimal("1.0000")
        )

    def _field(self, name: str) -> ApplicationField:
        """Resolve an invoice field used by an action or layout."""
        return self.get_application_field(name, self.invoice_model)

    def _filters(self, field: str, value: Any) -> list[dict[str, Any]]:
        """Build one equality filter using the portable structured schema."""
        return [
            {
                "connector": "AND",
                "conditions": [
                    {"field_path": field, "lookup_id": "equals", "value": value}
                ],
            }
        ]

    def _bulk_config(self, *, policy: str = "if_empty") -> dict[str, Any]:
        """Configure the work-order-line to invoice-line mapping."""
        return {
            "mode": "populate",
            "model": ContentType.objects.get_for_model(self.work_order_line_model).pk,
            "filters": self._filters("work_order", "{{ object.work_order }}"),
            "fetch": "all",
            "order_by": "quantity",
            "column_mappings": {
                "product": "product",
                "quantity": "quantity",
                "unit_price": "unit_price",
            },
            "write_policy": policy,
        }

    def _scalar_config(self) -> dict[str, Any]:
        """Configure a latest-effective-date rate lookup."""
        return {
            "model": ContentType.objects.get_for_model(self.rate_model).pk,
            "filters": self._filters("currency", "{{ object.currency }}"),
            "fetch": "last",
            "order_by": "effective_at",
            "column": "rate",
            "write_policy": "always",
        }

    def _row_config(self) -> dict[str, Any]:
        """Configure a product-specific lookup for existing invoice lines."""
        return {
            "mode": "per_row",
            "model": ContentType.objects.get_for_model(self.work_order_line_model).pk,
            "filters": [
                {
                    "connector": "AND",
                    "conditions": [
                        {
                            "field_path": "work_order",
                            "lookup_id": "equals",
                            "value": "{{ object.work_order }}",
                        },
                        {
                            "field_path": "product",
                            "lookup_id": "equals",
                            "value": "{{ row.product }}",
                        },
                    ],
                }
            ],
            "fetch": "first",
            "column": "unit_price",
            "target_column": "unit_price",
            "write_policy": "if_empty",
        }

    def _context(
        self, target: str, rows: list[dict[str, Any]] | None = None
    ) -> BehaviorContext:
        """Build an unsaved invoice draft with the selected work order."""
        return BehaviorContext(
            values={
                "work_order": self.work_order.pk,
                "currency": "EUR",
                "exchange_rate": None,
                "lines": rows if rows is not None else [],
            },
            listener_field="work_order",
            target_field=target,
        )

    def test_bulk_fetch_populates_matching_lines(self) -> None:
        """Copy only selected work-order lines, preserving product identities."""
        context = self._context("lines")
        result = FETCH.run(
            context,
            self._bulk_config(),
            listener=self._field("work_order"),
            target=self._field("lines"),
            user=self.admin_user,
        )
        self.assertEqual(len(result.values), 1)
        self.assertEqual(result.values[0].field, "lines")
        self.assertEqual(
            result.values[0].value,
            [
                {
                    "product": str(self.product_a.pk),
                    "quantity": 2,
                    "unit_price": "10.25",
                },
                {
                    "product": str(self.product_b.pk),
                    "quantity": 3,
                    "unit_price": "4.00",
                },
            ],
        )
        self.assertEqual(context.values["lines"], [])

    def test_scalar_fetch_uses_explicit_ordering(self) -> None:
        """Choose the latest effective rate even when its primary key is older."""
        result = FETCH.run(
            self._context("exchange_rate"),
            self._scalar_config(),
            listener=self._field("currency"),
            target=self._field("exchange_rate"),
            user=self.admin_user,
        )
        self.assertEqual(result.values[0].value, "1.2500")

    def test_per_row_fetch_uses_each_rows_product(self) -> None:
        """Fill only blank active rows using their own product placeholders."""
        rows = [
            {"product": self.product_a.pk, "quantity": 2, "unit_price": None},
            {"product": self.product_b.pk, "quantity": 3, "unit_price": "8.00"},
            {
                "product": self.product_a.pk,
                "quantity": 1,
                "unit_price": None,
                "DELETE": True,
            },
        ]
        context = self._context("lines", rows)
        result = FETCH.run(
            context,
            self._row_config(),
            listener=self._field("work_order"),
            target=self._field("lines"),
            user=self.admin_user,
        )
        self.assertEqual(result.values[0].value[0]["unit_price"], "10.25")
        self.assertEqual(result.values[0].value[1:], rows[1:])
        self.assertEqual(context.values["lines"], rows)

    def test_bulk_policies_preserve_existing_rows(self) -> None:
        """Never replace persisted rows and replace drafts only when explicitly asked."""
        draft_rows = [{"product": self.product_a.pk, "quantity": 7}]
        preserved = FETCH.run(
            self._context("lines", draft_rows),
            self._bulk_config(),
            listener=self._field("work_order"),
            target=self._field("lines"),
            user=self.admin_user,
        )
        self.assertEqual(preserved, BehaviorResult())
        replaced = FETCH.run(
            self._context("lines", draft_rows),
            self._bulk_config(policy="replace_unsaved"),
            listener=self._field("work_order"),
            target=self._field("lines"),
            user=self.admin_user,
        )
        self.assertEqual(len(replaced.values[0].value), 2)
        persisted = [{"id": "123", "product": self.product_a.pk}]
        blocked = FETCH.run(
            self._context("lines", persisted),
            self._bulk_config(policy="replace_unsaved"),
            listener=self._field("work_order"),
            target=self._field("lines"),
            user=self.admin_user,
        )
        self.assertEqual(blocked, BehaviorResult())

    def test_invalid_modes_and_mappings_are_rejected(self) -> None:
        """Reject scalar all, incompatible mappings, and row placeholders in bulk."""
        with self.assertRaises(ValidationError):
            clean_action_config(
                FETCH,
                self._field("currency"),
                self._field("exchange_rate"),
                {**self._scalar_config(), "fetch": "all"},
            )
        with self.assertRaises(ValidationError):
            clean_action_config(
                FETCH,
                self._field("work_order"),
                self._field("lines"),
                {**self._bulk_config(), "column_mappings": {"quantity": "product"}},
            )
        with self.assertRaises(ValidationError):
            clean_action_config(
                FETCH,
                self._field("work_order"),
                self._field("lines"),
                {
                    **self._bulk_config(),
                    "filters": self._filters("product", "{{ row.product }}"),
                },
            )

    def test_unrendered_target_column_is_rejected(self) -> None:
        """Limit bulk mappings to columns actually present in the form layout."""
        with self.assertRaises(ValidationError):
            clean_action_config(
                FETCH,
                self._field("work_order"),
                self._field("lines"),
                self._bulk_config(),
                target_layout_config={"inline_fields": ["quantity"]},
            )

    def test_denied_source_field_returns_no_rows(self) -> None:
        """Return one permission message without disclosing a partial collection."""
        with patch.object(
            UserPolicyManager, "has_field_permission", return_value=False
        ):
            result = FETCH.run(
                self._context("lines"),
                self._bulk_config(),
                listener=self._field("work_order"),
                target=self._field("lines"),
                user=self.normal_user,
            )
        self.assertEqual(
            result,
            BehaviorResult(
                messages=(
                    BehaviorMessage(
                        type="danger",
                        message="Permission denied: you cannot read the configured lookup data",
                    ),
                )
            ),
        )

    def test_denied_order_field_returns_no_value(self) -> None:
        """Do not use an unreadable field to determine the selected record."""

        def can_view_field(field: ApplicationField, permission: str) -> bool:
            """Deny only the source field used for ordering."""
            return field.field != "effective_at"

        with patch.object(
            UserPolicyManager, "has_field_permission", side_effect=can_view_field
        ):
            result = FETCH.run(
                self._context("exchange_rate"),
                self._scalar_config(),
                listener=self._field("currency"),
                target=self._field("exchange_rate"),
                user=self.normal_user,
            )
        self.assertEqual(result.values, ())
        self.assertEqual(result.messages[0].type, "danger")

    def test_executor_populates_invoice_lines_without_saving(self) -> None:
        """Check the full layout boundary and leave the invoice draft unsaved."""
        owner = UserObjectLayoutPreference.objects.create(
            user=self.admin_user,
            name="Fetch invoice lines",
            content_type=ContentType.objects.get_for_model(self.invoice_model),
            layout=FieldLayout(
                rows=[
                    LayoutRow(
                        columns=3,
                        items=[
                            LayoutItem(
                                id="work_order",
                                config={
                                    "behaviors": BehaviorConfig(
                                        behaviors=[
                                            FormBehavior(
                                                id="copy-work-order-lines",
                                                actions=[
                                                    BehaviorAction(
                                                        action="fetch",
                                                        target_field="lines",
                                                        config=self._bulk_config(),
                                                    )
                                                ],
                                            )
                                        ]
                                    ).to_storage()
                                },
                            ),
                            LayoutItem(id="currency"),
                            LayoutItem(
                                id="lines",
                                config={
                                    "inline_fields": [
                                        "product",
                                        "quantity",
                                        "unit_price",
                                    ]
                                },
                            ),
                        ],
                    )
                ]
            ).model_dump(mode="json"),
        )
        draft = {"work_order": str(self.work_order.pk), "currency": "EUR", "lines": []}
        result = BehaviorExecutor(owner, self.admin_user).evaluate("work_order", draft)
        self.assertEqual(len(result.values), 1)
        self.assertEqual(len(result.values[0].value), 2)
        self.assertEqual(draft["lines"], [])

    def test_same_model_lookup_does_not_require_source_field_in_layout(self) -> None:
        """Treat a persisted lookup column as source data, not a draft dependency."""
        self.invoice_model.objects.create(
            name="Rate source", currency="EUR", source_rate=Decimal("1.5000")
        )
        source_config = {
            "model": ContentType.objects.get_for_model(self.invoice_model).pk,
            "filters": self._filters("currency", "{{ object.currency }}"),
            "fetch": "first",
            "column": "source_rate",
            "write_policy": "always",
        }
        owner = UserObjectLayoutPreference.objects.create(
            user=self.admin_user,
            name="Same-model lookup",
            content_type=ContentType.objects.get_for_model(self.invoice_model),
            layout=FieldLayout(
                rows=[
                    LayoutRow(
                        columns=2,
                        items=[
                            LayoutItem(
                                id="currency",
                                config={
                                    "behaviors": BehaviorConfig(
                                        behaviors=[
                                            FormBehavior(
                                                id="copy-rate",
                                                actions=[
                                                    BehaviorAction(
                                                        action="fetch",
                                                        target_field="exchange_rate",
                                                        config=source_config,
                                                    )
                                                ],
                                            )
                                        ]
                                    ).to_storage()
                                },
                            ),
                            LayoutItem(id="exchange_rate"),
                        ],
                    )
                ]
            ).model_dump(mode="json"),
        )
        result = BehaviorExecutor(owner, self.admin_user).evaluate(
            "currency", {"currency": "EUR", "exchange_rate": None}
        )
        self.assertEqual(result.values[0].value, "1.5000")
