from django.db import models
from django.urls import reverse

from bloomerp.dataviews.pivot_table.renderer import (
    PivotField,
    PivotTable,
    PivotValueField,
)
from bloomerp.models import ApplicationField
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels
from bloomerp.tests.utils.dynamic_models import create_test_models


class TestPivotDataView(BaseBloomerpTestCaseWithModels):
    auto_create_customers = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.PivotRecordModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "PivotRecord": {
                    "region": models.CharField(max_length=100),
                    "team": models.CharField(max_length=100),
                    "quarter": models.CharField(max_length=20),
                    "active": models.BooleanField(default=True),
                    "amount": models.DecimalField(max_digits=10, decimal_places=2),
                    "__str__": lambda self: f"{self.region} {self.team}",
                },
            },
            use_bloomerp_base=True,
        )["PivotRecord"]
        cls._register_dynamic_model_routes([cls.PivotRecordModel])

    def _field(self, name: str) -> ApplicationField:
        return ApplicationField.get_by_field(self.PivotRecordModel, name)

    def extendedSetup(self):
        self.PivotRecordModel.objects.all().delete()

    def _configure_pivot(
        self,
        *,
        row_fields: list[str],
        column_fields: list[str] | None = None,
        value_fields: list[str] | None = None,
        aggregation: str = "sum",
        page_size: int = 10,
        totals_scope: str = "page",
    ):
        
        preference = PreferenceManager(self.admin_user).get_or_create_selected(
            UserListViewPreference,
            scope={
                "content_type_id" : self._field("region").content_type.id
            }
        )
        preference.view_type = "pivot_table"
        preference.options = {
            "pivot_table": {
                "row_fields": row_fields,
                "column_fields": column_fields or [],
                "value_fields": value_fields or ["amount"],
                "aggregation": aggregation,
                "show_row_totals": True,
                "show_column_totals": True,
                "totals_scope": totals_scope,
                "page_size": page_size,
            },
        }
        preference.save()
        return preference

    def _component_url(self) -> str:
        return reverse(
            "components_dataview",
            kwargs={"content_type_id": self._field("region").content_type_id},
        )

    def test_pivot_dataview_renders_nested_rows_and_column_headers(self):
        """
        Use case: A pivot has multiple row and column dimensions with numeric values.
        Expected result: Database sums render in expandable rows and spanning column headers.
        """
        # 1. Create records containing nested row and column combinations.
        self.PivotRecordModel.objects.bulk_create([
            self.PivotRecordModel(region="North", team="Alpha", quarter="Q1", active=True, amount=10),
            self.PivotRecordModel(region="North", team="Alpha", quarter="Q2", active=True, amount=20),
            self.PivotRecordModel(region="North", team="Beta", quarter="Q1", active=False, amount=5),
            self.PivotRecordModel(region="South", team="Gamma", quarter="Q1", active=True, amount=7),
        ])
        self._configure_pivot(
            row_fields=["region", "team"],
            column_fields=["quarter", "active"],
            value_fields=["amount", "active"],
        )
        self.client.force_login(self.admin_user)

        # 2. Request the permission-filtered data-view component.
        response = self.client.get(self._component_url(), HTTP_HX_REQUEST="true")

        # 3. Verify hierarchical rows, dimension headers, value leaf headers, aggregates, and totals.
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'bloomerp-component="pivot-table"', html=False)
        self.assertContains(response, 'data-pivot-toggle="0"', html=False)
        self.assertContains(response, 'data-pivot-parent-id="0"', count=2, html=False)
        self.assertContains(response, 'colspan="4"', html=False)
        self.assertContains(response, "Amount", html=False)
        self.assertContains(response, "Active", html=False)
        self.assertContains(response, "North", html=False)
        self.assertContains(response, "35", html=False)

    def test_pivot_dataview_paginates_top_level_rows_and_can_total_dataset(self):
        """
        Use case: A pivot has more top-level rows than its configured page size.
        Expected result: Pagination counts row groups while dataset totals include every filtered record.
        """
        # 1. Create twelve top-level row groups and request ten per page.
        self.PivotRecordModel.objects.bulk_create([
            self.PivotRecordModel(
                region=f"Region {index:02d}",
                team="Core",
                quarter="Q1",
                active=True,
                amount=index,
            )
            for index in range(1, 13)
        ])
        self._configure_pivot(
            row_fields=["region"],
            page_size=10,
            totals_scope="dataset",
        )
        self.client.force_login(self.admin_user)

        # 2. Request the first pivot page.
        response = self.client.get(self._component_url(), HTTP_HX_REQUEST="true")

        # 3. Verify ten row groups, table-style pagination, and the all-data total.
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-pivot-row-id=", count=10, html=False)
        self.assertContains(response, 'data-testid="data-view-pagination"', html=False)
        self.assertContains(response, "of 12 results", html=False)
        self.assertContains(response, "78", html=False)

    def test_reusable_pivot_builds_value_leaf_columns_only_when_needed(self):
        """
        Use case: A pivot switches between one and several selected value fields.
        Expected result: Multiple values add leaf headers; one value uses the dimension header directly.
        """
        # 1. Create two column groups with numeric and boolean values.
        self.PivotRecordModel.objects.bulk_create([
            self.PivotRecordModel(
                region="North", team="Alpha", quarter="Q1", active=True, amount=10
            ),
            self.PivotRecordModel(
                region="North", team="Alpha", quarter="Q2", active=False, amount=20
            ),
        ])
        region_field = PivotField(
            "region", "Region", self.PivotRecordModel._meta.get_field("region")
        )
        quarter_field = PivotField(
            "quarter", "Quarter", self.PivotRecordModel._meta.get_field("quarter")
        )
        amount_field = PivotField(
            "amount", "Amount", self.PivotRecordModel._meta.get_field("amount")
        )

        # 2. Aggregate the same field three ways and verify the bottom value-header level.
        multiple_values = PivotTable(
            queryset=self.PivotRecordModel.objects.all(),
            row_fields=[region_field],
            column_fields=[quarter_field],
            value_fields=[
                PivotValueField(**amount_field.__dict__, aggregation="sum"),
                PivotValueField(**amount_field.__dict__, aggregation="min"),
                PivotValueField(**amount_field.__dict__, aggregation="max"),
            ],
        ).build(["North"])
        self.assertEqual(
            [[cell.label for cell in row] for row in multiple_values.header_rows],
            [
                ["Q1", "Q2"],
                [
                    "Amount (Sum)",
                    "Amount (Min)",
                    "Amount (Max)",
                    "Amount (Sum)",
                    "Amount (Min)",
                    "Amount (Max)",
                ],
            ],
        )
        self.assertEqual(multiple_values.rows[0].cells, [10, 10, 10, 20, 20, 20])
        self.assertEqual(multiple_values.rows[0].totals, [30, 10, 20])
        self.assertEqual(multiple_values.effective_aggregations, ["sum", "min", "max"])

        # 3. Build the same pivot with one value and verify no redundant value-header row.
        single_value = PivotTable(
            queryset=self.PivotRecordModel.objects.all(),
            row_fields=[region_field],
            column_fields=[quarter_field],
            value_fields=[PivotValueField(**amount_field.__dict__, aggregation="sum")],
        ).build(["North"])
        self.assertEqual(
            [[cell.label for cell in row] for row in single_value.header_rows],
            [["Q1", "Q2"]],
        )
        self.assertEqual(single_value.rows[0].cells, [10, 20])

    def test_reusable_pivot_dataclass_limits_text_values_to_count(self):
        """
        Use case: A caller requests a numeric aggregation for a text value field.
        Expected result: The reusable pivot safely uses database count aggregation instead.
        """
        # 1. Create two text values in one row group.
        self.PivotRecordModel.objects.bulk_create([
            self.PivotRecordModel(region="North", team="Alpha", quarter="Q1", active=True, amount=10),
            self.PivotRecordModel(region="North", team="Beta", quarter="Q1", active=True, amount=20),
        ])
        region_field = self.PivotRecordModel._meta.get_field("region")
        team_field = self.PivotRecordModel._meta.get_field("team")
        pivot = PivotTable(
            queryset=self.PivotRecordModel.objects.all(),
            row_fields=[PivotField("region", "Region", region_field)],
            column_fields=[],
            value_fields=[PivotValueField("team", "Team", team_field, aggregation="sum")],
        )

        # 2. Build the pivot from its top-level row value.
        result = pivot.build(["North"])

        # 3. Verify the effective aggregation and database-computed result.
        self.assertEqual(result.effective_aggregations, ["count"])
        self.assertEqual(result.rows[0].cells, [2])
        self.assertEqual(result.rows[0].totals, [2])

    def test_pivot_options_use_native_application_field_multi_selects(self):
        """
        Use case: A user opens the pivot display configuration.
        Expected result: Rows, columns, and values use native multiple-choice selectors.
        """
        # 1. Configure the pivot view and sign in.
        self._configure_pivot(row_fields=["region"])
        self.client.force_login(self.admin_user)
        # 2. Request the data view, which contains its display options component.
        response = self.client.get(self._component_url(), HTTP_HX_REQUEST="true")

        # 3. Verify all three field selectors render as native multiple selects.
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="row_fields"', html=False)
        self.assertContains(response, 'name="column_fields"', html=False)
        self.assertContains(response, 'name="value_fields"', html=False)
        self.assertContains(response, "multiple", count=3, html=False)
        self.assertContains(response, "Aggregation", html=False)

        # 4. Submit ordered row and column selections through the preference endpoint.
        preference_url = reverse(
            "components_update_dataview_preference",
            kwargs={"content_type_id": self._field("region").content_type_id},
        )
        post_response = self.client.post(
            preference_url,
            data={
                "dataview_options_view_type": "pivot_table",
                "row_fields": ["region", "team"],
                "column_fields": ["quarter"],
                "value_fields": ["amount", "active"],
                "aggregation": "sum",
                "show_row_totals": "on",
                "show_column_totals": "on",
                "totals_scope": "dataset",
                "page_size": "25",
            },
            HTTP_HX_REQUEST="true",
        )

        # 5. Verify all ordered multi-select values are persisted as field names.
        self.assertEqual(post_response.status_code, 200)
        preference = PreferenceManager(self.admin_user).get_or_create_selected(
            UserListViewPreference,
            scope={
                "content_type_id":self._field("region").content_type.id,
            }
        )
        
        self.assertEqual(
            preference.options["pivot_table"]["row_fields"],
            ["region", "team"],
        )
        self.assertEqual(
            preference.options["pivot_table"]["value_fields"],
            ["amount", "active"],
        )
