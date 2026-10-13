"""Unified scalar, aggregate, and per-row calculation scenarios."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone as django_timezone

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
from bloomerp.models.application_field import ApplicationField
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
                    "start_date": models.DateField(null=True, blank=True),
                    "end_date": models.DateField(null=True, blank=True),
                    "start_time": models.DateTimeField(null=True, blank=True),
                    "end_time": models.DateTimeField(null=True, blank=True),
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
                    "date": models.DateField(null=True, blank=True),
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
            expected_exception=ExpectedBehaviorActionException(ValidationError, error)
            if error
            else None,
        )

    def get_test_scenarios(self) -> list[BehaviorActionScenario]:
        """Cover arithmetic, aggregation, per-row writes, and unsafe formulas."""
        rows = self._rows()
        rows[0]["total"] = Decimal("24.60")
        rows[1]["total"] = Decimal("14.40")
        return self._temporal_scenarios() + [
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

    def _temporal_scenarios(self) -> list[BehaviorActionScenario]:
        """Cover typed date offsets, blank propagation, and unsupported operations."""
        scenarios: list[BehaviorActionScenario] = []
        cases = [
            (
                "date plus days",
                "start_date + 14",
                "end_date",
                "start_date",
                "2026-12-25",
                date(2027, 1, 8),
            ),
            (
                "date minus days",
                "start_date - 14",
                "end_date",
                "start_date",
                date(2026, 1, 5),
                date(2025, 12, 22),
            ),
            (
                "date negative offset",
                "start_date + -2",
                "end_date",
                "start_date",
                "2026-03-01",
                date(2026, 2, 27),
            ),
            (
                "date zero offset",
                "start_date + 0",
                "end_date",
                "start_date",
                "2026-03-01",
                date(2026, 3, 1),
            ),
            (
                "datetime plus minutes",
                "start_time + 14",
                "end_time",
                "start_time",
                "2026-12-31T23:55:00+00:00",
                datetime(2027, 1, 1, 0, 9, tzinfo=UTC),
            ),
            (
                "datetime minus minutes",
                "start_time - 14",
                "end_time",
                "start_time",
                "2026-01-01T00:05:00+00:00",
                datetime(2025, 12, 31, 23, 51, tzinfo=UTC),
            ),
            (
                "numeric field offset",
                "start_date + tax_rate",
                "end_date",
                "start_date",
                "2026-03-01",
                date(2026, 3, 3),
            ),
            (
                "exact decimal whole offset",
                "start_date + (0.1 + 0.2) * 10",
                "end_date",
                "start_date",
                "2026-03-01",
                date(2026, 3, 4),
            ),
        ]
        cases.extend(
            [
                (
                    "leap day",
                    "start_date + 1",
                    "end_date",
                    "start_date",
                    "2028-02-28",
                    date(2028, 2, 29),
                ),
                (
                    "datetime negative offset",
                    "start_time + -14",
                    "end_time",
                    "start_time",
                    "2026-01-01T00:05:00Z",
                    datetime(2025, 12, 31, 23, 51, tzinfo=UTC),
                ),
                (
                    "datetime zero offset",
                    "start_time + 0",
                    "end_time",
                    "start_time",
                    "2026-01-01T00:05:00Z",
                    datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
                ),
            ]
        )
        for name, expression, target, source, value, expected in cases:
            scenarios.append(
                self._scenario(
                    name,
                    expression,
                    target=target,
                    values={source: value, "tax_rate": Decimal(2)},
                    result=BehaviorResult(
                        values=(FieldValueUpdate(field=target, value=expected),)
                    ),
                )
            )
        for source, target in (("start_date", "end_date"), ("start_time", "end_time")):
            for blank in (None, ""):
                scenarios.append(
                    self._scenario(
                        f"blank {source} preserves destination {blank!r}",
                        f"{source} + 14",
                        target=target,
                        values={source: blank, target: "existing"},
                        result=BehaviorResult(),
                    )
                )
        for name, expression, target, values, error in [
            (
                "date plus date",
                "start_date + end_date",
                "start_time",
                {},
                "date or datetime",
            ),
            (
                "date difference",
                "start_date - end_date",
                "start_time",
                {},
                "date or datetime",
            ),
            ("date multiply", "start_date * 2", "end_date", {}, "date or datetime"),
            ("date divide", "start_date / 2", "end_date", {}, "date or datetime"),
            ("date unary", "-start_date", "end_date", {}, "date or datetime"),
            (
                "fractional day",
                "start_date + 0.5",
                "end_date",
                {"start_date": "2026-03-01"},
                "whole number",
            ),
            (
                "fractional minute",
                "start_time + 0.5",
                "end_time",
                {"start_time": "2026-03-01T00:00:00Z"},
                "whole number",
            ),
            (
                "invalid date",
                "start_date + 1",
                "end_date",
                {"start_date": "not-a-date"},
                "valid date",
            ),
            (
                "invalid datetime",
                "start_time + 1",
                "end_time",
                {"start_time": "not-a-date"},
                "valid date",
            ),
            ("temporal to numeric", "start_date + 1", "total", {}, "result type"),
            ("numeric to date", "tax_rate + 1", "end_date", {}, "result type"),
            ("date to datetime", "start_date + 1", "end_time", {}, "result type"),
            (
                "date overflow",
                "start_date + 1",
                "end_date",
                {"start_date": "9999-12-31"},
                "range",
            ),
        ]:
            scenarios.append(
                self._scenario(
                    name, expression, target=target, values=values, error=error
                )
            )
        scenarios.append(
            self._scenario(
                "populated date write policy",
                "start_date + 1",
                target="end_date",
                values={"start_date": "2026-01-01", "end_date": date(2026, 2, 1)},
                config={"write_policy": "if_empty"},
                result=BehaviorResult(),
            )
        )
        scenarios.append(
            self._scenario(
                "nonfinite numeric offset",
                "start_date + tax_rate",
                target="end_date",
                values={"start_date": "2026-01-01", "tax_rate": "NaN"},
                error="finite numeric",
            )
        )
        for expression in (
            "start_date + 1e999999999",
            "start_date - 1e999999999",
            "start_date + -1e999999999",
        ):
            scenarios.append(
                self._scenario(
                    "bounded huge offset " + expression,
                    expression,
                    target="end_date",
                    values={"start_date": "2026-03-01"},
                    error="range",
                )
            )
        scenarios.append(
            self._scenario(
                "numeric blank remains zero",
                "tax_rate + 2",
                values={"tax_rate": None},
                result=BehaviorResult(
                    values=(FieldValueUpdate(field="total", value=Decimal(2)),)
                ),
            )
        )
        return scenarios

    def _temporal_owner(
        self, *, action: str, target: str, config: dict[str, Any]
    ) -> UserObjectLayoutPreference:
        """Build a saved layout for exercising typed temporal behavior responses."""
        return UserObjectLayoutPreference.objects.create(
            user=self.admin_user,
            name="Temporal calculation",
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
                                                id="temporal",
                                                actions=[
                                                    BehaviorAction(
                                                        action=action,
                                                        target_field=target,
                                                        config=config,
                                                    )
                                                ],
                                            )
                                        ]
                                    ).to_storage()
                                },
                            ),
                            LayoutItem(id="start_date"),
                            LayoutItem(id="end_date"),
                            LayoutItem(id="start_time"),
                            LayoutItem(id="end_time"),
                        ],
                    )
                ]
            ).model_dump(mode="json"),
        )

    def test_executor_serializes_date_result(self) -> None:
        """Return ISO dates while leaving submitted draft values and records unchanged."""
        owner = self._temporal_owner(
            action="calculate",
            target="end_date",
            config={"expression": "start_date + 14"},
        )
        draft = {"name": "trigger", "start_date": "2026-10-12", "end_date": ""}
        result = BehaviorExecutor(owner, self.admin_user).evaluate("name", draft)
        self.assertEqual(
            result.values, (FieldValueUpdate(field="end_date", value="2026-10-26"),)
        )
        self.assertEqual(
            draft, {"name": "trigger", "start_date": "2026-10-12", "end_date": ""}
        )
        self.assertEqual(self.invoice_model.objects.count(), 0)

    def test_datetime_offset_crosses_daylight_saving_gap(self) -> None:
        """Add elapsed minutes without producing an invalid local spring-forward time."""
        owner = self._temporal_owner(
            action="calculate",
            target="end_time",
            config={"expression": "start_time + 14"},
        )
        with django_timezone.override("Europe/Amsterdam"):
            result = BehaviorExecutor(owner, self.admin_user).evaluate(
                "name",
                {
                    "name": "trigger",
                    "start_time": "2026-03-29T01:55:00",
                    "end_time": "",
                },
            )
        self.assertEqual(
            result.values,
            (FieldValueUpdate(field="end_time", value="2026-03-29T03:09:00"),),
        )

    def test_ambiguous_datetime_widget_result_is_rejected(self) -> None:
        """Do not emit a fall-back wall time that the existing widget cannot submit."""
        owner = self._temporal_owner(
            action="calculate",
            target="end_time",
            config={"expression": "start_time + 60"},
        )
        draft = {"name": "trigger", "start_time": "2026-10-25T01:55:00", "end_time": ""}
        with (
            django_timezone.override("Europe/Amsterdam"),
            self.assertRaises(ValidationError),
        ):
            BehaviorExecutor(owner, self.admin_user).evaluate("name", draft)
        self.assertEqual(draft["end_time"], "")

    def test_executor_serializes_datetime_for_its_local_widget(self) -> None:
        """Keep aware arithmetic internally and deliver datetime-local input values."""
        owner = self._temporal_owner(
            action="calculate",
            target="end_time",
            config={"expression": "start_time + 14"},
        )
        with django_timezone.override("Europe/Amsterdam"):
            result = BehaviorExecutor(owner, self.admin_user).evaluate(
                "name",
                {
                    "name": "trigger",
                    "start_time": "2026-10-12T10:30:00+00:00",
                    "end_time": "",
                },
            )
        self.assertEqual(
            result.values,
            (FieldValueUpdate(field="end_time", value="2026-10-12T12:44:00"),),
        )
        self.assertEqual(self.invoice_model.objects.count(), 0)

    def test_executor_formats_now_without_unsupported_microseconds(self) -> None:
        """Format relative-now output exactly as the existing datetime widget does."""
        owner = self._temporal_owner(
            action="set_relative_date", target="end_time", config={"offset": 14}
        )
        with (
            django_timezone.override("Europe/Amsterdam"),
            patch(
                "bloomerp.form_behaviors.builtins.set_relative_date.timezone.now",
                return_value=datetime(2026, 10, 12, 10, 30, 0, 123456, tzinfo=UTC),
            ),
        ):
            result = BehaviorExecutor(owner, self.admin_user).evaluate(
                "name", {"name": "trigger", "end_time": ""}
            )
        self.assertEqual(
            result.values,
            (FieldValueUpdate(field="end_time", value="2026-10-12T12:44:00"),),
        )

    def test_executor_preserves_blank_date_target(self) -> None:
        """An empty temporal dependency must not erase an existing draft target."""
        owner = self._temporal_owner(
            action="calculate",
            target="end_date",
            config={"expression": "start_date + 14"},
        )
        result = BehaviorExecutor(owner, self.admin_user).evaluate(
            "name", {"name": "trigger", "start_date": "", "end_date": "2026-10-12"}
        )
        self.assertEqual(result, BehaviorResult())

    def test_temporal_scalar_and_numeric_collection_eligibility(self) -> None:
        """Expose scalar dates while keeping collection columns numeric-only."""
        fields = ApplicationField.get_for_model(self.invoice_model)
        targets = set(
            CALCULATE.get_target_fields(fields, self._field("name")).values_list(
                "field", flat=True
            )
        )
        self.assertTrue(
            {"start_date", "end_date", "start_time", "end_time", "lines"}.issubset(
                targets
            )
        )
        with self.assertRaises(ValidationError):
            clean_action_config(
                CALCULATE,
                self._field("name"),
                self._field("lines"),
                {
                    "target_column": "date",
                    "expression": "lines.quantity + 1",
                },
                target_layout_config={"inline_fields": ["date", "quantity"]},
            )
        with self.assertRaisesRegex(ValidationError, "non-numeric column"):
            clean_action_config(
                CALCULATE,
                self._field("name"),
                self._field("end_date"),
                {"expression": "first(lines.date) + 1"},
            )

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
