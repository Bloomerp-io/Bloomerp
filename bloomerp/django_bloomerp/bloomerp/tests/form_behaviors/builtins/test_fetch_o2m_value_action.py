"""Tests for fetching values into one-to-many draft rows."""

from decimal import Decimal
from typing import Any
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.db import models

from bloomerp.form_behaviors.builtins.fetch_o2m_value import FETCH_O2M_VALUE
from bloomerp.form_behaviors.definition import (
    BehaviorContext,
    BehaviorFieldReference,
    BehaviorMessage,
    BehaviorResult,
    FieldValueUpdate,
)
from bloomerp.form_behaviors.utils import clean_action_config
from bloomerp.models.application_field import ApplicationField
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.tests.base import BehaviorActionScenario, BloomerpBehaviorActionTestCase
from bloomerp.tests.utils.dynamic_models import create_test_models


class TestFetchO2mValueAction(BloomerpBehaviorActionTestCase):
    """Verify per-row lookup substitution, preservation, deletion, and denial."""

    action = FETCH_O2M_VALUE
    auto_create_customers = False
    invoice_model: type[models.Model]
    line_model: type[models.Model]
    rate_model: type[models.Model]

    @classmethod
    def setUpClass(cls) -> None:
        """Create invoice rows and lookup records with compatible decimal columns."""
        super().setUpClass()
        fixtures = create_test_models(
            "bloomerp",
            {
                "FetchInvoice": {"name": models.CharField(max_length=40)},
                "FetchInvoiceLine": {
                    "invoice": models.ForeignKey(
                        "bloomerp.FetchInvoice",
                        on_delete=models.CASCADE,
                        related_name="lines",
                    ),
                    "currency": models.CharField(max_length=3),
                    "exchange_rate": models.DecimalField(
                        max_digits=10, decimal_places=4
                    ),
                },
                "FetchExchangeRate": {
                    "currency": models.CharField(max_length=3),
                    "rate": models.DecimalField(max_digits=10, decimal_places=4),
                },
            },
            use_bloomerp_base=True,
        )
        cls.invoice_model = fixtures["FetchInvoice"]
        cls.line_model = fixtures["FetchInvoiceLine"]
        cls.rate_model = fixtures["FetchExchangeRate"]

    def setUp(self) -> None:
        """Create deterministic source rates after ApplicationFields are generated."""
        super().setUp()
        self.rate_model.objects.create(currency="EUR", rate=Decimal("1.0000"))
        self.rate_model.objects.create(currency="USD", rate=Decimal("1.2500"))

    def _listener(self) -> ApplicationField:
        """Return the invoice's reverse collection field."""
        return self.get_application_field("lines", self.invoice_model)

    def _config(self) -> dict[str, Any]:
        """Build portable configuration using a row currency placeholder."""
        return {
            "target_column": "exchange_rate",
            "fetch_from": ContentType.objects.get_for_model(self.rate_model).pk,
            "fetch_field": "rate",
            "filters": [
                {
                    "connector": "AND",
                    "conditions": [
                        {
                            "field_path": "currency",
                            "lookup_id": "equals",
                            "value": "{{ row.currency }}",
                        }
                    ],
                }
            ],
            "fetch_strategy": "first",
        }

    def get_test_scenarios(self) -> list[BehaviorActionScenario]:
        """Populate matching rows while retaining unmatched and deleted rows."""
        listener = self._listener()
        rows = [
            {"currency": "EUR", "exchange_rate": "0.0000", "note": "keep"},
            {"currency": "USD", "exchange_rate": "1.2500"},
            {"currency": "GBP", "exchange_rate": "0.9000"},
            {"currency": "EUR", "exchange_rate": "9.0000", "DELETE": True},
        ]
        expected = [
            {**rows[0], "exchange_rate": "1.0000"},
            *rows[1:],
        ]
        return [
            BehaviorActionScenario(
                name="Each active row resolves its own source record without clearing unmatched rows",
                context=BehaviorContext(values={"lines": rows}, listener_field="lines"),
                listener=listener,
                config=self._config(),
                expected_result=BehaviorResult(
                    values=(FieldValueUpdate(field="lines", value=expected),)
                ),
            )
        ]

    def test_denied_lookup_returns_permission_message_without_partial_rows(
        self,
    ) -> None:
        """Return the shared denied result before exposing any fetched source value."""
        context = BehaviorContext(
            values={"lines": [{"currency": "EUR", "exchange_rate": "0.0000"}]},
            listener_field="lines",
        )
        with patch.object(
            UserPolicyManager, "has_field_permission", return_value=False
        ):
            result = self.action.run(
                context,
                self._config(),
                listener=self._listener(),
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

    def test_definition_explains_per_row_lookup_and_group(self) -> None:
        """Expose clear action-picker copy for the row-oriented lookup."""
        self.assertEqual(self.action.group, "Data lookup")
        self.assertIn("one-to-many", self.action.label.lower())
        self.assertIn("every active child row", self.action.description.lower())

    def test_row_placeholders_declare_child_field_dependencies(self) -> None:
        """Expose child columns so the executor loads their supplied draft values."""
        cleaned = clean_action_config(
            self.action,
            self._listener(),
            None,
            self._config(),
        )
        references = cleaned["value_references"]
        self.assertEqual(len(references), 1)
        self.assertIsInstance(references[0], BehaviorFieldReference)
        self.assertEqual(references[0].field.field, "currency")
