"""Tests for one fetch action across scalar, collection, and per-row targets."""

import json
from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import get_language, override

from bloomerp.form_behaviors.builtins.fetch import FETCH
from bloomerp.form_behaviors.definition import (
    BehaviorAction,
    BehaviorConfig,
    BehaviorContext,
    BehaviorMessage,
    BehaviorResult,
    FieldValueUpdate,
    FormBehavior,
)
from bloomerp.form_behaviors.execution import BehaviorExecutor
from bloomerp.form_behaviors.utils import action_config_form, clean_action_config
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.users.user_object_layout_preference import (
    UserObjectLayoutPreference,
)
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.tests.base import (
    BehaviorActionScenario,
    BloomerpBehaviorActionTestCase,
    ExpectedBehaviorActionException,
)
from bloomerp.tests.utils.dynamic_models import create_test_models
from bloomerp.widgets.behavior_builder_widget import BehaviorBuilderWidget


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

    def _record_config(self) -> dict[str, Any]:
        """Select a work-order record using the current invoice name input."""
        return {
            "model": self.work_order_model._meta.label_lower,
            "value_source": "record",
            "filters": self._filters("name", "{{ object.name }}"),
            "fetch": "first",
            "order_by": "name",
            "write_policy": "always",
        }

    def _record_context(self, current: str | None = None) -> BehaviorContext:
        """Build a draft whose source lookup matches the selected work order."""
        return BehaviorContext(
            values={"name": "Selected", "work_order": current},
            listener_field="name",
            target_field="work_order",
        )

    def get_test_scenarios(self) -> list[BehaviorActionScenario]:
        """Describe record identity assignment, ordering, policies, and validation."""
        listener = self._field("name")
        target = self._field("work_order")
        config = self._record_config()
        other = self.work_order_model.objects.get(name="Other")
        selected_result = BehaviorResult(
            values=(FieldValueUpdate(field="work_order", value=str(self.work_order.pk)),),
        )
        return [
            BehaviorActionScenario(
                name="Select the filtered record itself into a UUID relation",
                context=self._record_context(),
                config=config, listener=listener, target=target,
                expected_result=selected_result,
            ),
            BehaviorActionScenario(
                name="Select the first matching record alphabetically",
                context=self._record_context(),
                config={**config, "filters": []},
                listener=listener, target=target,
                expected_result=BehaviorResult(
                    values=(FieldValueUpdate(field="work_order", value=str(other.pk)),),
                ),
            ),
            BehaviorActionScenario(
                name="Select the last matching record alphabetically",
                context=self._record_context(),
                config={**config, "filters": [], "fetch": "last"},
                listener=listener, target=target,
                expected_result=selected_result,
            ),
            BehaviorActionScenario(
                name="Replace an existing selection under the always policy",
                context=self._record_context(str(other.pk)),
                config=config, listener=listener, target=target,
                expected_result=selected_result,
            ),
            BehaviorActionScenario(
                name="Preserve an existing selection under the empty-only policy",
                context=self._record_context(str(other.pk)),
                config={**config, "write_policy": "if_empty"},
                listener=listener, target=target, expected_result=BehaviorResult(),
            ),
            BehaviorActionScenario(
                name="Leave an existing selection unchanged when no record matches",
                context=self._record_context(str(other.pk)),
                config={**config, "filters": self._filters("name", "Missing")},
                listener=listener, target=target, expected_result=BehaviorResult(),
            ),
            BehaviorActionScenario(
                name="Avoid updating an already selected matching record",
                context=self._record_context(str(self.work_order.pk)),
                config=config, listener=listener, target=target,
                expected_result=BehaviorResult(),
            ),
            BehaviorActionScenario(
                name="Reject a source model different from the relation target",
                context=self._record_context(),
                config={**config, "model": self.product_model._meta.label_lower},
                listener=listener, target=target,
                expected_exception=ExpectedBehaviorActionException(ValidationError),
            ),
            BehaviorActionScenario(
                name="Reject record selection into a scalar text target",
                context=BehaviorContext(
                    values={"name": "Selected", "currency": ""},
                    listener_field="name", target_field="currency",
                ),
                config=config, listener=listener, target=self._field("currency"),
                expected_exception=ExpectedBehaviorActionException(ValidationError),
            ),
            BehaviorActionScenario(
                name="Keep source column mandatory for existing field-copy configurations",
                context=self._context("exchange_rate"),
                config={**self._scalar_config(), "column": None},
                listener=listener, target=self._field("exchange_rate"),
                expected_exception=ExpectedBehaviorActionException(
                    ValidationError, message_regex="Select a source column",
                ),
            ),
        ]

    def test_record_lookup_respects_accessible_rows(self) -> None:
        """
        Use case: A record lookup matches both permitted and inaccessible rows.
        Expected result: Only permitted rows participate in first-record selection.
        """
        # 1. Restrict the lookup to a record that sorts after an inaccessible row.
        with patch.object(
            UserPolicyManager, "get_accessible_queryset",
            return_value=self.work_order_model.objects.filter(pk=self.work_order.pk),
        ):
            # 2. Execute through configuration binding and the authorized lookup.
            result = FETCH.run(
                self._record_context(),
                {**self._record_config(), "filters": []},
                listener=self._field("name"), target=self._field("work_order"),
                user=self.admin_user,
            )
        # 3. Confirm the inaccessible alphabetically first row was not returned.
        self.assertEqual(result.values[0].value, str(self.work_order.pk))

    def test_record_lookup_denies_unreadable_order_field(self) -> None:
        """
        Use case: Record selection orders by a field the user cannot read.
        Expected result: The action returns a permission message and no identity.
        """
        # 1. Deny access to the explicit ordering field.
        with patch.object(UserPolicyManager, "has_field_permission", return_value=False):
            # 2. Attempt to select the matching record.
            result = FETCH.run(
                self._record_context(), self._record_config(),
                listener=self._field("name"), target=self._field("work_order"),
                user=self.normal_user,
            )
        # 3. Verify no record identity was disclosed.
        self.assertEqual(result.values, ())
        self.assertEqual(result.messages[0].type, "danger")

    def test_record_lookup_without_policies_returns_no_identity(self) -> None:
        """
        Use case: A normal user without grants attempts a record lookup.
        Expected result: No record identity is disclosed even without source columns.
        """
        # 1. Remove order and filters to exercise row authorization alone.
        config = {**self._record_config(), "order_by": None, "filters": []}
        # 2. Run the lookup as a normal user with no applicable policies.
        result = FETCH.run(
            self._record_context(), config,
            listener=self._field("name"), target=self._field("work_order"),
            user=self.normal_user,
        )
        # 3. Confirm the source model cannot disclose an identity.
        self.assertEqual(result.values, ())

    def test_record_editor_hides_source_column(self) -> None:
        """
        Use case: A compatible relation target selects the matching record itself.
        Expected result: The editor offers record selection and hides source columns.
        """
        # 1. Render the same configuration form used by the behavior builder.
        form = action_config_form(
            FETCH, self._field("name"), self._field("work_order"),
            self._record_config(),
        )
        # 2. Verify the record option is offered and has no column requirement.
        self.assertIn(
            ("record", "Matching record itself"),
            form.fields["value_source"].choices,
        )
        self.assertTrue(form.fields["column"].widget.is_hidden)
        self.assertTrue(form.fields["column"].disabled)
        self.assertIn("value_source", form.refresh_fields)

    def test_record_executor_updates_draft_without_saving(self) -> None:
        """
        Use case: A saved layout fetches a matching record into a relation field.
        Expected result: Changed selections update the draft; the same UUID emits no update.
        """
        # 1. Save a layout with an on-change record-selection action.
        owner = UserObjectLayoutPreference.objects.create(
            user=self.admin_user,
            name="Select matching work order",
            content_type=ContentType.objects.get_for_model(self.invoice_model),
            layout=FieldLayout(rows=[
                LayoutRow(columns=2, items=[
                    LayoutItem(id="name", config={
                        "behaviors": BehaviorConfig(behaviors=[
                            FormBehavior(id="select-work-order", actions=[
                                BehaviorAction(
                                    action="fetch", target_field="work_order",
                                    config=self._record_config(),
                                ),
                            ]),
                        ]).to_storage(),
                    }),
                    LayoutItem(id="work_order"),
                ]),
            ]).model_dump(mode="json"),
        )
        # 2. Execute with the listener's current unsaved form value.
        result = BehaviorExecutor(owner, self.admin_user).evaluate(
            "name", {"name": "Selected", "work_order": None},
        )
        # 3. Verify relation validation succeeded without persisting an invoice.
        self.assertEqual(result.values[0].value, str(self.work_order.pk))
        self.assertEqual(self.invoice_model.objects.count(), 0)
        # 4. Reevaluate a form that already selects the matching UUID relation.
        unchanged = BehaviorExecutor(owner, self.admin_user).evaluate(
            "name", {"name": "Selected", "work_order": str(self.work_order.pk)},
        )
        # 5. The executor's native UUID must compare equal to the fetched identity.
        self.assertEqual(unchanged, BehaviorResult())

    def test_anonymous_record_lookup_returns_no_identity(self) -> None:
        """
        Use case: An anonymous caller tries selecting a source record.
        Expected result: No record identity is disclosed without authenticated access.
        """
        # 1. Use record mode without any field reads.
        config = {**self._record_config(), "order_by": None, "filters": []}
        # 2. Run against the anonymous user's accessible queryset.
        result = FETCH.run(
            self._record_context(), config,
            listener=self._field("name"), target=self._field("work_order"),
            user=AnonymousUser(),
        )
        # 3. Confirm no identity was returned.
        self.assertEqual(result.values, ())

    def _translate_for_language(self, message: str) -> str:
        """Identify the language used when each lazy message is resolved."""
        return f"{get_language()}:{message}"

    def test_behavior_metadata_uses_the_active_language(self) -> None:
        """
        Use case: The same registered behavior is rendered in different languages.
        Expected result: UI text follows the active language while stored IDs stay stable.
        """
        # 1. Render real action forms and widget catalogs using a localized catalog.
        listener = self._field("name")
        widget = BehaviorBuilderWidget(
            source_field={"id": str(listener.pk)},
            field_catalog=[{"id": listener.pk}, {"id": self._field("work_order").pk}],
        )
        with patch(
            "django.utils.translation._trans.gettext",
            side_effect=self._translate_for_language,
        ):
            for language in ("nl", "de"):
                with self.subTest(language=language), override(language):
                    # 2. Resolve lazy labels during JSON serialization and HTML rendering.
                    context = widget.get_context("behaviors", None, None)
                    actions = json.loads(context["widget"]["actions_json"])
                    fetch = next(action for action in actions if action["id"] == "fetch")
                    form = action_config_form(
                        FETCH, listener, self._field("work_order"), self._record_config(),
                    )
                    html = widget.render("behaviors", BehaviorConfig().to_storage())
                    # 3. Check translated text and stable machine-readable values.
                    self.assertEqual(fetch["label"], f"{language}:Fetch")
                    self.assertEqual(fetch["group"], f"{language}:Data lookup")
                    self.assertEqual(str(form.fields["value_source"].label), f"{language}:Value to copy")
                    self.assertIn(
                        ("record", f"{language}:Matching record itself"),
                        [(value, str(label)) for value, label in form.fields["value_source"].choices],
                    )
                    self.assertIn(f"{language}:Add behavior", html)
                    self.assertIn(f"{language}:Clear all", html)
                    self.assertEqual(self._record_config()["value_source"], "record")

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

    def test_declarative_source_model_label_is_accepted(self) -> None:
        """Resolve a portable model label without persisting a database-specific ID."""
        config = {
            **self._bulk_config(),
            "model": self.work_order_line_model._meta.label_lower,
        }

        cleaned = clean_action_config(
            FETCH,
            self._field("work_order"),
            self._field("lines"),
            config,
        )

        self.assertEqual(
            cleaned["model"],
            ContentType.objects.get_for_model(self.work_order_line_model),
        )

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
