"""Regression scenarios for sequential values in a one-to-many draft."""

from django.db import models

from bloomerp.form_behaviors.builtins.increment_o2m_value import INCREMENT_O2M_VALUE
from bloomerp.form_behaviors.definition import BehaviorContext, BehaviorResult, FieldValueUpdate
from bloomerp.tests.base import BehaviorActionScenario, BloomerpBehaviorActionTestCase
from bloomerp.tests.utils.dynamic_models import create_test_models


class TestIncrementO2mValueAction(BloomerpBehaviorActionTestCase):
    """Blank active rows receive values after the largest existing sequence value."""

    action = INCREMENT_O2M_VALUE
    auto_create_customers = False

    @classmethod
    def setUpClass(cls) -> None:
        """Create an invoice collection with an integer sequence column."""
        super().setUpClass()
        fixtures = create_test_models("bloomerp", {
            "BehaviorInvoice": {"name": models.CharField(max_length=40)},
            "BehaviorInvoiceLine": {
                "invoice": models.ForeignKey("bloomerp.BehaviorInvoice", on_delete=models.CASCADE, related_name="lines"),
                "position": models.IntegerField(null=True, blank=True),
                "note": models.CharField(max_length=40, blank=True),
            },
        }, use_bloomerp_base=True)
        cls.invoice_model = fixtures["BehaviorInvoice"]
        cls.line_model = fixtures["BehaviorInvoiceLine"]

    def get_test_scenarios(self) -> list[BehaviorActionScenario]:
        """Cover blank-only drafts, zero, and rows marked for deletion."""
        listener = self.get_application_field("lines", self.invoice_model)
        position = self.get_application_field("position", self.line_model)
        rows = [
            {"id": "line-1", "position": 0, "note": "Zero is valid"},
            {"id": "line-2", "position": None},
            {"id": "line-3"},
            {"id": "line-4", "position": 9},
            {"id": "line-5", "position": None, "DELETE": True},
        ]
        expected = [
            rows[0],
            {"id": "line-2", "position": 10},
            {"id": "line-3", "position": 11},
            rows[3],
            rows[4],
        ]
        return [BehaviorActionScenario(
            name="Blank rows are numbered after the maximum active integer",
            context=BehaviorContext(values={"lines": rows}, listener_field="lines"),
            listener=listener,
            config={"field": position.field},
            expected_result=BehaviorResult(values=(FieldValueUpdate(field="lines", value=expected),)),
        ), BehaviorActionScenario(
            name="Blank-only rows start at one",
            context=BehaviorContext(
                values={"lines": [{"position": None}, {}]},
                listener_field="lines",
            ),
            listener=listener,
            config={"field": position.field},
            expected_result=BehaviorResult(values=(FieldValueUpdate(
                field="lines", value=[{"position": 1}, {"position": 2}],
            ),)),
        )]
