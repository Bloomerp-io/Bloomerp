"""Readable dataview scenarios for the draft unified filtering pipeline."""
from collections.abc import Callable
from unittest import skip

from django.db.models import Model, QuerySet
from django.http import HttpResponse
from pydantic import TypeAdapter

from bloomerp.filters.definition import Filter, FilterCondition, Filters
from bloomerp.models.application_field import ApplicationField
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


def filter_query_params(*groups: Filter) -> dict[str, str]:
    """Serialize typed groups into the GET format; groups combine with AND."""
    return {"filter": TypeAdapter(Filters).dump_json(list(groups)).decode("utf-8")}


def uses_render_value_function(response: HttpResponse, instance: Model, field: str) -> bool:
    application_field = ApplicationField.get_for_model(type(instance)).get(field=field)
    rendered_value = application_field.get_field_type().render_value(application_field, instance)
    return str(rendered_value) in response.content.decode(response.charset or "utf-8")


class TestDataviewComponent(BloomerpComponentTestCase):
    """Specify visible rows separately from the filters being exercised."""

    view_name = "components_dataview"
    create_foreign_models = True
    auto_create_customers = False

    def contains_entries(
        self, queryset: QuerySet, fields: list[str] | None = None,
    ) -> Callable[[HttpResponse], bool]:
        """Check exact page membership, plus optional rendered field values.

        Fixtures fit on one page. Exact IDs also catch unwanted extra rows;
        testing only whether expected names occur would miss those leaks.
        """
        expected_entries = list(queryset)
        expected_ids = {entry.pk for entry in expected_entries}

        def validate(response: HttpResponse) -> bool:
            actual_ids = [entry.pk for entry in response.context["queryset"]]
            return (
                set(actual_ids) == expected_ids
                and len(actual_ids) == len(expected_ids)
                and all(
                    uses_render_value_function(response, entry, field)
                    for entry in expected_entries
                    for field in fields or []
                )
            )

        validate.__name__ = f"contains_entries(exact_count={len(expected_entries)}, fields={fields})"
        return validate

    def get_test_scenarios(self) -> list[RequestScenario]:
        for i in range(10):
            planet = self.PlanetModel.objects.create(name=f"Planet {i}")
            country = self.CountryModel.objects.create(name=f"Country {i}", planet=planet)
            self.CustomerModel.objects.create(
                first_name=f"First Name {i}", last_name=f"Last Name {i}",
                age=i, country=country,
            )

        kwargs = {"content_type_id": self.get_content_type_for_model(self.CustomerModel).pk}
        customers = self.CustomerModel.objects

        
        
        return [
            RequestScenario(
                name="ACCESS: Superuser sees all entries",
                user=self.admin_user,
                view_kwargs=kwargs,
                expected=ExpectedResult(response_validators=self.contains_entries(customers.all())),
            ),
            RequestScenario(
                name="ACCESS: User without access receives 403",
                user=self.normal_user,
                view_kwargs=kwargs,
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="FILTERS: Empty filter list preserves all entries",
                user=self.admin_user,
                view_kwargs=kwargs,
                query_params=filter_query_params(),
                expected=ExpectedResult(response_validators=self.contains_entries(customers.all())),
            ),
            RequestScenario(
                name="FILTERS: Equality returns only the matching entry",
                user=self.admin_user,
                view_kwargs=kwargs,
                query_params=filter_query_params(Filter(connector="AND", conditions=[
                    FilterCondition(field_path="first_name", lookup_id="equals", value="First Name 3"),
                ])),
                expected=ExpectedResult(response_validators=self.contains_entries(customers.filter(age=3))),
            ),
            RequestScenario(
                name="FILTERS: AND requires both conditions",
                user=self.admin_user,
                view_kwargs=kwargs,
                query_params=filter_query_params(Filter(connector="AND", conditions=[
                    FilterCondition(field_path="age", lookup_id="greater_than", value=2),
                    FilterCondition(field_path="age", lookup_id="less_than", value=6),
                ])),
                expected=ExpectedResult(response_validators=self.contains_entries(customers.filter(age__in=[3, 4, 5]))),
            ),
            RequestScenario(
                name="FILTERS: OR accepts either condition",
                user=self.admin_user,
                view_kwargs=kwargs,
                query_params=filter_query_params(Filter(connector="OR", conditions=[
                    FilterCondition(field_path="age", lookup_id="equals", value=1),
                    FilterCondition(field_path="age", lookup_id="equals", value=8),
                ])),
                expected=ExpectedResult(response_validators=self.contains_entries(customers.filter(age__in=[1, 8]))),
            ),
            RequestScenario(
                name="FILTERS: Groups combine with implicit AND",
                user=self.admin_user,
                view_kwargs=kwargs,
                query_params=filter_query_params(
                    Filter(connector="OR", conditions=[
                        FilterCondition(field_path="age", lookup_id="equals", value=1),
                        FilterCondition(field_path="age", lookup_id="equals", value=8),
                    ]),
                    Filter(connector="AND", conditions=[
                        FilterCondition(field_path="age", lookup_id="greater_than", value=5),
                    ]),
                ),
                expected=ExpectedResult(response_validators=self.contains_entries(customers.filter(age=8))),
            ),
            RequestScenario(
                name="FILTERS: Nested relation delegates to terminal text lookup",
                user=self.admin_user,
                view_kwargs=kwargs,
                query_params=filter_query_params(Filter(connector="AND", conditions=[
                    FilterCondition(field_path="country__planet__name", lookup_id="equals", value="Planet 4"),
                ])),
                expected=ExpectedResult(response_validators=self.contains_entries(customers.filter(age=4))),
            ),
            RequestScenario(
                name="FILTERS: No matches produces an empty page",
                user=self.admin_user,
                view_kwargs=kwargs,
                query_params=filter_query_params(Filter(connector="AND", conditions=[
                    FilterCondition(field_path="age", lookup_id="greater_than", value=100),
                ])),
                expected=ExpectedResult(response_validators=self.contains_entries(customers.none())),
            ),
            RequestScenario(
                name="FILTERS: Invalid lookup value returns 400",
                user=self.admin_user,
                view_kwargs=kwargs,
                query_params=filter_query_params(Filter(connector="AND", conditions=[
                    FilterCondition(field_path="age", lookup_id="greater_than", value="not a number"),
                ])),
                expected=ExpectedResult(status_code=400),
            ),
            RequestScenario(
                name="RENDERING: Related field uses its render_value function",
                user=self.admin_user,
                view_kwargs=kwargs,
                expected=ExpectedResult(response_validators=self.contains_entries(customers.all(), fields=["country"])),
            ),
            RequestScenario(
                name="FILTERS: Filters still work with GET args",
                user=self.admin_user,
                view_kwargs=kwargs,
                query_params={
                    "country__name" : "Country 1"
                },
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_entries(
                            customers.filter(country__name="Country 1")
                        )
                    ]
                )
            )
            
        ]

    @skip("TODO: Finish dataview parsing, permission validation, and filter compilation/application")
    def test_request_scenarios(self):
        """Enable once the draft filtering pipeline supports these request contracts."""
        super().test_request_scenarios()

    @skip("TODO: Assign a policy granting all customer rows and fields")
    def test_normal_user_with_full_access(self):
        """The user sees every fixture row and its permitted field values."""

    @skip("TODO: Assign a field policy allowing only first_name")
    def test_limited_field_access(self):
        """Allowed values render; last_name values do not appear in the HTML."""

    @skip("TODO: Give rows Y first_name/last_name access and rows X first_name access")
    def test_multiple_policies_preserve_per_row_field_access(self):
        """last_name renders for Y but remains hidden for X, even with both policies."""

    @skip("TODO: Assign a row policy and request an OR filter matching permitted and hidden rows")
    def test_filters_cannot_expand_row_access(self):
        """Only permitted matching rows render; OR cannot override row permissions."""

    @skip("TODO: Grant Customer access but deny Country access")
    def test_filtering_on_inaccessible_related_model_is_denied(self):
        """A country__name condition is rejected rather than leaking related data."""

    @skip("TODO: Add JSON-field fixtures")
    def test_json_key_filter(self):
        """A JSON key path and terminal lookup select exactly the expected rows."""

    @skip("TODO: Add a preference with default filters")
    def test_default_filters_combine_with_requested_filters(self):
        """Preference defaults and request filters follow the agreed combination rules."""
