"""Readable dataview scenarios for the draft unified filtering pipeline."""
from collections.abc import Callable
from unittest import skip

from django.contrib.contenttypes.models import ContentType
from django.db.models import Model, QuerySet
from django.http import HttpResponse
from pydantic import TypeAdapter

from bloomerp.dataviews.definition import BaseDataview, DataviewTypeDefinition
from bloomerp.dataviews.registry import DATAVIEW_REGISTRY
from bloomerp.dataviews.table.config import TableDataView
from bloomerp.filters.definition import Filter, FilterCondition, Filters
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.document_templates.document_template import DocumentTemplate
from bloomerp.models.filters.filter import SavedFilter
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.permissions.definition import AccessRule, BloomerpPermission, RowPolicyRuleCondition, RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.services.preference_services import PreferenceManager
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

def add_default_filter(request_scenario: RequestScenario):
    content_type_id = request_scenario.view_kwargs.get("content_type_id")

    list_view_preference: UserListViewPreference = PreferenceManager(
        request_scenario.user
    ).get_or_create_selected(
        UserListViewPreference,
        {"content_type_id": content_type_id},
    )

    saved_filter = SavedFilter.objects.create(
        name="Default filter",
        scope="model",
        filters=[
            Filter(
                connector="AND",
                conditions=[
                    FilterCondition(
                        field_path="age",
                        lookup_id="greater_than",
                        value=2,
                    )
                ],
            ).model_dump()
        ],
        identifier=str(content_type_id),
    )
    list_view_preference.add_default_filter(saved_filter)


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
            )

        validate.__name__ = f"contains_entries(exact_count={len(expected_entries)}, fields={fields})"
        return validate

    
    def uses_render_value_function(self, field, instance):
        def validate(response):
            return uses_render_value_function(response, instance, field)
        
        return validate
    
    def set_view_type(self, view_type: BaseDataview):
        def set_fields(scenario: RequestScenario):
            preference: UserListViewPreference = PreferenceManager(
                scenario.user
            ).get_or_create_selected(
                UserListViewPreference,
                scope=scenario.view_kwargs,
            )

            application_fields = {
                field.field: field
                for field in ApplicationField.get_for_model(self.CustomerModel)
            }
            unknown_fields = set(view_type.display_fields) - application_fields.keys()
            if unknown_fields:
                raise ValueError(
                    f"Unknown display fields: {', '.join(sorted(unknown_fields))}"
                )

            options = preference.options.copy()
            options[view_type.view_type] = view_type.dump_options()

            preference.options = options
            preference.view_type = view_type.view_type
            preference.set_visible_field_ids(
                view_type.view_type,
                [application_fields[name].pk for name in view_type.display_fields],
            )
            preference.save(update_fields=["display_fields", "options", "view_type"])

        return set_fields

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

        customer_content_type = ContentType.objects.get_for_model(self.CustomerModel)
        document_template_content_type = ContentType.objects.get_for_model(DocumentTemplate)
        matching_template = DocumentTemplate.objects.create(name="Customer template")
        matching_template.content_types.add(customer_content_type)
        unrelated_template = DocumentTemplate.objects.create(name="Unrelated template")
        document_template_kwargs = {
            "content_type_id": document_template_content_type.pk,
        }
        
        request_scenarios = []
        for dataview_type in DATAVIEW_REGISTRY.values():
            if dataview_type.requires_display_fields:
                try:
                    request_scenarios.append(
                        RequestScenario(
                            name=f"RENDERING: Related field uses its render_value function for {dataview_type.label}",
                            user=self.admin_user,
                            view_kwargs=kwargs,
                            expected=ExpectedResult(response_validators=[
                                self.uses_render_value_function("country", self.CustomerModel.objects.first())
                            ]),
                            prepare=self.set_view_type(
                                dataview_type.config_cls(
                                    display_fields=["country"]
                                )
                            )
                        ),
                    )
                except:
                    print("skipping for ", dataview_type.label)
        
            
        request_scenarios += [
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
                    FilterCondition(field_path="age", lookup_id="invalid_lookup", value="not a number"),
                ])),
                expected=ExpectedResult(status_code=400),
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
            ),
            RequestScenario(
                name="FILTERS: Many-to-many equality accepts one shorthand value",
                description=(
                    "UC: A document-template dataview is scoped to one object type.\n"
                    "Expected Result: The matching template renders without a validation error."
                ),
                user=self.admin_user,
                view_kwargs=document_template_kwargs,
                query_params={"content_types": str(customer_content_type.pk)},
                expected=ExpectedResult(
                    response_validators=self.contains_entries(
                        DocumentTemplate.objects.filter(pk=matching_template.pk)
                    )
                ),
            ),
            RequestScenario(
                name="FILTERS: Many-to-many not-equals accepts one shorthand value",
                description=(
                    "UC: A document-template dataview excludes one object type.\n"
                    "Expected Result: Only the unrelated template renders."
                ),
                user=self.admin_user,
                view_kwargs=document_template_kwargs,
                query_params={
                    "content_types_not_equals": str(customer_content_type.pk),
                },
                expected=ExpectedResult(
                    response_validators=self.contains_entries(
                        DocumentTemplate.objects.filter(pk=unrelated_template.pk)
                    )
                ),
            ),
            RequestScenario(
                name="FILTERS: Additional filter does not override default filters",
                user=self.admin_user,
                view_kwargs=kwargs,
                prepare=add_default_filter,
                query_params=filter_query_params(
                    Filter(
                        connector="AND",
                        conditions=[
                            FilterCondition(field_path="age", lookup_id="less_than", value=6)
                        ]
                    )    
                ),
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_entries(
                            customers.filter(age__in=[3, 4, 5])
                        )
                    ]
                )
            ),
            RequestScenario(
                name="Normal user can only see the fields he has access to",
                method="GET",
                user=self.normal_user,
                view_kwargs=kwargs,
                prepare=[
                    # Prep 1: add policy
                    lambda _: PolicyManager.create_policy(
                    self.CustomerModel,
                    access_rule=AccessRule(
                        row_permissions=[],
                        field_permissions={
                            "first_name" : [BloomerpPermission.VIEW]
                        }
                    ),
                    global_permissions=[
                        BloomerpPermission.VIEW
                    ]
                ).assign_user(self.normal_user),
                # Prep 2: explicitly include the unaccessible fields
                self.set_view_type(
                    TableDataView(
                        display_fields=["first_name", "last_name"]
                    )
                )
                ],
                expected=ExpectedResult(
                    status_code=200,
                    response_validators=[
                        self.contains_text("First Name"),
                        self.does_not_contain_text("Last Name")
                    ]
                )
            ),
            RequestScenario(
                name="Combined permissions preserve field level access",
                method="GET",
                user=self.normal_user,
                view_kwargs=kwargs,
                prepare=self.set_policies(
                    policies=[
                        AccessRule(
                            row_permissions=[
                                RowPolicyRuleContent(
                                    connector="AND",
                                    conditions=[
                                        FilterCondition(
                                            field_path="first_name",
                                            value="First Name 1",
                                            lookup_id="equals"
                                        )
                                    ],
                                    permissions=[BloomerpPermission.VIEW]
                                )
                            ],
                            field_permissions={
                                "first_name" : [BloomerpPermission.VIEW]
                            }
                        ),
                        AccessRule(
                            row_permissions=[
                                RowPolicyRuleContent(
                                    connector="AND",
                                    conditions=[
                                        FilterCondition(
                                            field_path="last_name",
                                            value="Last Name 2",
                                            lookup_id="equals"
                                        )
                                    ],
                                    permissions=[BloomerpPermission.VIEW]
                                )
                            ],
                            field_permissions={
                                "last_name" : [BloomerpPermission.VIEW]
                            }
                        ),
                    ],
                global_permissions=[BloomerpPermission.VIEW]
                ),
                expected=ExpectedResult(
                    status_code=200,
                    response_validators=[
                        self.contains_text("First Name 1"),
                        self.contains_text("Last Name 2"),
                        self.does_not_contain_text("Last Name 1"),
                        self.does_not_contain_text("First Name 2")
                    ]
                )
            ),
            RequestScenario(
                name="Filtering on in-accesible field is denied",
                user=self.normal_user,
                prepare=self.set_policies(
                    policies=[
                        AccessRule(
                            row_permissions=[],
                            field_permissions={
                                "first_name" : [BloomerpPermission.VIEW]
                            }
                        )
                    ],
                    global_permissions=[BloomerpPermission.VIEW]
                ),
                view_kwargs=kwargs,
                query_params=filter_query_params(
                    Filter(
                        connector="AND",
                        conditions=[
                            FilterCondition(
                                field_path="age",
                                lookup_id="equals",
                                value=5
                            )
                        ]
                    )
                ),
                expected=ExpectedResult(
                    status_code=403
                )
            )
        ]
        
        return request_scenarios
    
    def set_policies(self, policies:list[AccessRule], global_permissions:list[BloomerpPermission]):
        def _set_policies(scenario:RequestScenario):
            for policy in policies:
                PolicyManager.create_policy(
                    self.CustomerModel,
                    access_rule=policy,
                    global_permissions=global_permissions
                ).assign_user(
                    scenario.user
                )

        return _set_policies
    
