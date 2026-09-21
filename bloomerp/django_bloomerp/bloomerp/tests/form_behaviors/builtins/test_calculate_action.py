"""Unified scalar, aggregate, and per-row calculation scenarios."""

from decimal import Decimal
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models

from bloomerp.form_behaviors.builtins.calculate import CALCULATE
from bloomerp.form_behaviors.definition import (
    BehaviorAction,
    BehaviorConfig,
    BehaviorContext,
    BehaviorResult,
    FieldValueUpdate,
    FormBehavior,
)
from bloomerp.form_behaviors.execution import BehaviorExecutor
from bloomerp.form_behaviors.utils import clean_action_config
from bloomerp.models.definition import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.users.user_object_layout_preference import (
    UserObjectLayoutPreference,
)
from bloomerp.tests.base import (
    BehaviorActionScenario,
    BloomerpBehaviorActionTestCase,
    ExpectedBehaviorActionException,
)
from bloomerp.tests.utils.dynamic_models import create_test_models


class TestCalculateAction(BloomerpBehaviorActionTestCase):
    """Exercise the single action across both target shapes."""

    action = CALCULATE
    auto_create_customers = False
    invoice_model: type[models.Model]

    @classmethod
    def setUpClass(cls) -> None:
        """Create an invoice and child line model with numeric operands."""
        super().setUpClass()
        fixtures = create_test_models(
            "bloomerp",
            {
                "UnifiedInvoice": {
                    "name": models.CharField(max_length=40),
                    "tax_rate": models.DecimalField(
                        max_digits=5, decimal_places=2, null=True, blank=True
                    ),
                    "total": models.DecimalField(
                        max_digits=12, decimal_places=2, null=True, blank=True
                    ),
                },
                "UnifiedInvoiceLine": {
                    "invoice": models.ForeignKey(
                        "bloomerp.UnifiedInvoice",
                        on_delete=models.CASCADE,
                        related_name="lines",
                    ),
                    "unit_price": models.DecimalField(
                        max_digits=10, decimal_places=2, null=True, blank=True
                    ),
                    "quantity": models.IntegerField(null=True, blank=True),
                    "total": models.DecimalField(
                        max_digits=12, decimal_places=2, null=True, blank=True
                    ),
                    "note": models.CharField(max_length=40, blank=True),
                },
            },
            use_bloomerp_base=True,
        )
        cls.invoice_model = fixtures["UnifiedInvoice"]

    def _field(self, name: str) -> Any:
        """Find a generated invoice ApplicationField by its name."""
        return self.get_application_field(name, self.invoice_model)

    def _rows(self) -> list[dict[str, Any]]:
        """Return two active rows and one deleted row for formula scenarios."""
        return [
            {
                "unit_price": Decimal("10.25"),
                "quantity": 2,
                "total": None,
                "note": "keep",
            },
            {
                "unit_price": Decimal("4.00"),
                "quantity": 3,
                "total": None,
                "note": "also keep",
            },
            {"unit_price": Decimal(99), "quantity": 1, "total": None, "DELETE": True},
        ]

    def _scenario(
        self,
        name: str,
        expression: str,
        *,
        target: str = "total",
        config: dict[str, Any] | None = None,
        values: dict[str, Any] | None = None,
        result: BehaviorResult | None = None,
        error: str | None = None,
    ) -> BehaviorActionScenario:
        """Build one configured calculation with an exact result or validation error."""
        draft = {
            "name": "trigger",
            "tax_rate": Decimal("0.20"),
            "total": None,
            "lines": self._rows(),
        }
        if values:
            draft.update(values)
        options = {"expression": expression, **(config or {})}
        return BehaviorActionScenario(
            name=name,
            context=BehaviorContext(
                values=draft, listener_field="name", target_field=target
            ),
            listener=self._field("name"),
            target=self._field(target),
            config=options,
            expected_result=result if error is None else None,
            expected_exception=ExpectedBehaviorActionException(Exception, error)
            if error
            else None,
        )

    def get_test_scenarios(self) -> list[BehaviorActionScenario]:
        """Cover arithmetic, aggregation, per-row writes, and unsafe formulas."""
        rows = self._rows()
        rows[0]["total"] = Decimal("24.60")
        rows[1]["total"] = Decimal("14.40")
        return [
            self._scenario(
                "scalar arithmetic",
                "tax_rate * 100 + 0.1 + 0.2",
                result=BehaviorResult(
                    values=(FieldValueUpdate(field="total", value=Decimal("20.3")),)
                ),
            ),
            self._scenario(
                "aggregate sum",
                "sum(lines.unit_price * lines.quantity)",
                result=BehaviorResult(
                    values=(FieldValueUpdate(field="total", value=Decimal("32.50")),)
                ),
            ),
            self._scenario(
                "two aggregates of one collection",
                "sum(lines.quantity) + sum(lines.unit_price)",
                result=BehaviorResult(
                    values=(FieldValueUpdate(field="total", value=Decimal("19.25")),)
                ),
            ),
            self._scenario(
                "aggregate count",
                "count(lines.quantity)",
                result=BehaviorResult(
                    values=(FieldValueUpdate(field="total", value=Decimal(2)),)
                ),
            ),
            self._scenario(
                "aggregate first",
                "first(lines.unit_price)",
                result=BehaviorResult(
                    values=(FieldValueUpdate(field="total", value=Decimal("10.25")),)
                ),
            ),
            self._scenario(
                "aggregate last",
                "last(lines.unit_price)",
                result=BehaviorResult(
                    values=(FieldValueUpdate(field="total", value=Decimal("4.00")),)
                ),
            ),
            self._scenario(
                "empty first",
                "first(lines.quantity)",
                values={"lines": []},
                result=BehaviorResult(),
            ),
            self._scenario(
                "row formula with parent field",
                "lines.unit_price * lines.quantity * (1 + tax_rate)",
                target="lines",
                config={"target_column": "total"},
                result=BehaviorResult(
                    values=(FieldValueUpdate(field="lines", value=rows),)
                ),
            ),
            self._scenario(
                "write policy preserves existing",
                "tax_rate * 100",
                config={"write_policy": "if_empty"},
                values={"total": Decimal(5)},
                result=BehaviorResult(),
            ),
            self._scenario(
                "reject target self-reference",
                "total + 1",
                error="cannot reference itself",
            ),
            self._scenario(
                "reject row self-reference",
                "lines.total + 1",
                target="lines",
                config={"target_column": "total"},
                error="cannot reference itself",
            ),
            self._scenario(
                "reject arbitrary function",
                "abs(tax_rate)",
                error="sum, count, first, or last",
            ),
            self._scenario(
                "reject nonnumeric column",
                "sum(lines.note)",
                error="non-numeric column",
            ),
            self._scenario(
                "reject divide by zero", "tax_rate / 0", error="divides by zero"
            ),
            self._scenario(
                "reject bare child reference",
                "lines.unit_price",
                error="inside an aggregation",
            ),
        ]

    def test_executor_calculates_row_target(self) -> None:
        """Verify declared target updates pass through layout draft validation."""
        owner = UserObjectLayoutPreference.objects.create(
            user=self.admin_user,
            name="Unified calculation",
            content_type=ContentType.objects.get_for_model(self.invoice_model),
            layout=FieldLayout(
                rows=[
                    LayoutRow(
                        columns=3,
                        items=[
                            LayoutItem(
                                id="name",
                                config={
                                    "behaviors": BehaviorConfig(
                                        behaviors=[
                                            FormBehavior(
                                                id="calculate-lines",
                                                actions=[
                                                    BehaviorAction(
                                                        action="calculate",
                                                        target_field="lines",
                                                        config={
                                                            "target_column": "total",
                                                            "expression": "lines.unit_price * lines.quantity * (1 + tax_rate)",
                                                        },
                                                    )
                                                ],
                                            )
                                        ]
                                    ).to_storage()
                                },
                            ),
                            LayoutItem(id="tax_rate"),
                            LayoutItem(
                                id="lines",
                                config={
                                    "inline_fields": [
                                        "unit_price",
                                        "quantity",
                                        "total",
                                        "note",
                                    ]
                                },
                            ),
                        ],
                    )
                ]
            ).model_dump(mode="json"),
        )
        result = BehaviorExecutor(owner, self.admin_user).evaluate(
            "name",
            {
                "name": "trigger",
                "tax_rate": "0.20",
                "lines": [
                    {
                        "unit_price": "10.25",
                        "quantity": "2",
                        "total": "0.00",
                        "note": "keep",
                    },
                ],
            },
        )
        self.assertEqual(len(result.values), 1)
        self.assertEqual(result.values[0].field, "lines")
        self.assertEqual(
            Decimal(str(result.values[0].value[0]["total"])), Decimal("24.60")
        )

    def test_unrendered_target_column_is_rejected(self) -> None:
        """Prevent editor choices from targeting columns absent from the layout."""
        with self.assertRaises(ValidationError):
            clean_action_config(
                CALCULATE,
                self._field("name"),
                self._field("lines"),
                {"target_column": "total", "expression": "lines.quantity * 2"},
                target_layout_config={"inline_fields": ["quantity"]},
            )
