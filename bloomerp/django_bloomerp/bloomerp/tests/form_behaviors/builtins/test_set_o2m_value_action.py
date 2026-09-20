"""Regression scenarios for copying a product price without clearing row values."""

from decimal import Decimal
from typing import Any

from django.db import models

from bloomerp.form_behaviors.builtins.set_o2m_value import SET_O2M_VALUE
from bloomerp.form_behaviors.definition import (
    BehaviorContext,
    BehaviorResult,
    FieldValueUpdate,
)
from bloomerp.form_behaviors.shared.write_policy import WritePolicyField
from bloomerp.models.application_field import ApplicationField
from bloomerp.tests.base import BehaviorActionScenario, BloomerpBehaviorActionTestCase
from bloomerp.tests.utils.dynamic_models import create_test_models


class TestSetO2mValueAction(BloomerpBehaviorActionTestCase):
    """Only destination cells change; product identities and unrelated row data survive."""

    action = SET_O2M_VALUE
    auto_create_customers = False
    product_model: type[models.Model]
    invoice_model: type[models.Model]
    line_model: type[models.Model]

    @classmethod
    def setUpClass(cls) -> None:
        """Create real invoice/product fields for the configuration form to resolve."""
        super().setUpClass()
        fixtures = create_test_models(
            "bloomerp",
            {
                "BehaviorProduct": {
                    "sales_price": models.DecimalField(max_digits=10, decimal_places=2)
                },
                "BehaviorInvoice": {"name": models.CharField(max_length=40)},
                "BehaviorInvoiceLine": {
                    "invoice": models.ForeignKey(
                        "bloomerp.BehaviorInvoice",
                        on_delete=models.CASCADE,
                        related_name="lines",
                    ),
                    "product": models.ForeignKey(
                        "bloomerp.BehaviorProduct", on_delete=models.CASCADE
                    ),
                    "rate": models.DecimalField(max_digits=10, decimal_places=2),
                },
            },
            use_bloomerp_base=True,
        )
        cls.product_model = fixtures["BehaviorProduct"]
        cls.invoice_model = fixtures["BehaviorInvoice"]
        cls.line_model = fixtures["BehaviorInvoiceLine"]

    def resolve_prices(
        self,
        source: ApplicationField,
        accessor: ApplicationField,
        identities: tuple[Any, ...],
    ) -> dict[str, Any]:
        """Supply the selected product's price without coupling this action test to permissions."""
        self.assertEqual(source.field, "product")
        self.assertEqual(accessor.field, "sales_price")
        self.assertEqual(set(identities), {"product-1"})
        return {"product-1": Decimal("25.00")}

    def get_test_scenarios(self) -> list[BehaviorActionScenario]:
        """Assert the entire returned collection, including every unchanged cell and row."""
        target = self.get_application_field("lines", self.invoice_model)
        rows = [
            {
                "id": "line-1",
                "product": "product-1",
                "rate": Decimal("0.00"),
                "quantity": 3,
                "note": "Keep me",
            },
            {
                "id": "line-2",
                "product": "product-1",
                "rate": Decimal("25.00"),
                "quantity": 7,
            },
            {"product": "", "rate": Decimal("12.00"), "note": "Unselected draft"},
            {
                "id": "line-4",
                "product": "deleted-product",
                "rate": Decimal("9.00"),
                "DELETE": True,
            },
        ]
        expected = [{**rows[0], "rate": Decimal("25.00")}, *rows[1:]]
        return [
            BehaviorActionScenario(
                name="Setting a product price preserves its selection and only changes the destination cell",
                context=BehaviorContext(
                    values={"lines": rows},
                    listener_field="lines",
                    target_field="lines",
                    resolve_related_values=self.resolve_prices,
                ),
                listener=target,
                target=target,
                config={
                    "from_column": "product",
                    "accessor": "sales_price",
                    "to_column": "rate",
                },
                expected_result=BehaviorResult(
                    values=(FieldValueUpdate(field="lines", value=expected),)
                ),
            )
        ]

    def test_write_policy_uses_shared_subset_and_legacy_default(self) -> None:
        """Set related-row value shares only always and empty-or-zero policies."""
        target = self.get_application_field("lines", self.invoice_model)
        form_class = self.action.config_form_factory(target, target)
        field = form_class.base_fields["write_policy"]
        self.assertIsInstance(field, WritePolicyField)
        self.assertEqual(
            [choice[0] for choice in field.choices],
            ["always", "if_empty_or_zero"],
        )
        self.assertEqual(field.clean(""), "always")
