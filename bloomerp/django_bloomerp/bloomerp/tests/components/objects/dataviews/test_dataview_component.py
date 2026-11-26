"""Readable dataview scenarios for the draft unified filtering pipeline."""
import json
from collections.abc import Callable
from datetime import timedelta
from functools import partial
from unittest.mock import patch
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core import signing
from django.db.models import Model, QuerySet
from django.http import HttpResponse
from django.utils import timezone
from pydantic import TypeAdapter

from bloomerp.dataviews.definition import BaseDataview
from bloomerp.dataviews.registry import DATAVIEW_REGISTRY
from bloomerp.dataviews.table.config import TableDataView
from bloomerp.filters.definition import Filter, FilterCondition, Filters
from bloomerp.models.actions.object.call_dataview import call_dataview_action
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import (
    FieldLayout,
    LayoutItem,
    LayoutRow,
    ObjectActionTarget,
)
from bloomerp.models.document_templates.document_template import DocumentTemplate
from bloomerp.models.filters.filter import SavedFilter
from bloomerp.models.project_management.initiative import Initiative
from bloomerp.models.project_management.todo import Todo
from bloomerp.models.users.user import User
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.permissions.definition import (
    AccessRule,
    BloomerpPermission,
    RowPolicyRuleContent,
)
from bloomerp.permissions.manager import PolicyManager
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.templatetags.bloomerp import render_object_action
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)
from bloomerp.tokens import (
    REQUEST_TOKEN_HEADER,
    REQUEST_TOKEN_QUERY_KEYS,
    DataviewToken,
    DetailViewToken,
    RequestToken,
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
                and (fields is None or {field.field for field in response.context["dataview_render_fields"]} == set(fields))
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

    def set_advanced_rendering(
        self, field_name: str, source: str,
    ) -> Callable[[RequestScenario], None]:
        """Configure one field override on the normal table request path."""
        def prepare(scenario: RequestScenario) -> None:
            """Select the field and install the requested template for this case."""
            self.set_view_type(TableDataView(display_fields=[field_name]))(scenario)
            ApplicationField.get_for_model(self.CustomerModel).filter(
                field=field_name,
            ).update(advanced_rendering=source)

        return prepare

    def prepare_escaped_advanced_rendering(self, scenario: RequestScenario) -> None:
        """Render user-supplied text inside trusted field-template markup."""
        self.CustomerModel.objects.filter(age=0).update(
            first_name="<script>unsafe</script>",
        )
        self.set_advanced_rendering(
            "first_name", '<strong class="custom-name">{{ value }}</strong>',
        )(scenario)

    def prepare_contact_rows(self, scenario: RequestScenario) -> None:
        """Show three users while granting only one row's email field."""
        rows = {
            "contact-visible": "visible-contact@example.com",
            "contact-private": "private-contact@example.com",
            "contact-empty": "",
        }
        for username, email in rows.items():
            User.objects.create(username=username, email=email)
        policy = PolicyManager.create_policy(
            User,
            field_permissions={"username": ["view"]},
            row_permissions=[RowPolicyRuleContent(
                permissions=["view"], connector="OR",
                conditions=[
                    FilterCondition(field_path="username", lookup_id="equals", value=username)
                    for username in rows
                ],
            )],
        )
        email_policy = PolicyManager.create_policy(
            User,
            field_permissions={"email": ["view"]},
            row_permissions=[RowPolicyRuleContent(
                permissions=["view"],
                conditions=[
                    FilterCondition(field_path="username", lookup_id="equals", value="contact-visible"),
                ],
            )],
        )
        PolicyManager.assign(policy, self.normal_user)
        PolicyManager.assign(email_policy, self.normal_user)
        content_type = ContentType.objects.get_for_model(User)
        scenario.view_kwargs = {"content_type_id": content_type.pk}
        preference = PreferenceManager(self.normal_user).get_or_create_selected(
            UserListViewPreference, {"content_type_id": content_type.pk},
        )
        username_field = ApplicationField.get_for_model(User).get(field="username")
        preference.view_type = "table"
        preference.set_visible_field_ids("table", [username_field.pk])
        preference.save(update_fields=["display_fields", "view_type"])

    def renders_only_one_contact_menu(self, response: HttpResponse) -> bool:
        """Hide the dropdown on rows with empty or unreadable contact details."""
        return response.content.count(b'aria-label="More actions"') == 1

    def prepare_contact_with_todo_permission(self, scenario: RequestScenario) -> None:
        """Grant Todo creation while retaining the fixture's row-specific email permissions."""
        self.prepare_contact_rows(scenario)
        self.normal_user.user_permissions.add(Permission.objects.get(
            content_type=ContentType.objects.get_for_model(Todo), codename="add_todo",
        ))

    def groups_create_todo_and_contact(self, response: HttpResponse) -> bool:
        """Require Create Todo and the contact composer to share one row dropdown."""
        soup = BeautifulSoup(response.content, "html.parser")
        return any(
            menu.select_one('button[role="menuitem"][bloomerp-open-modal="detail-todo-modal"]')
            and menu.select_one('button[hx-get*="email_field=email"]')
            for menu in soup.select("[data-dropdown-panel]")
        )

    def prepare_dataview_action(
        self, scenario: RequestScenario, *, target: ObjectActionTarget,
        detail_view_token: DetailViewToken | None = None,
    ) -> None:
        """Render an action and extract its filtered URL and context header."""
        layout = DataviewToken(
            dataview=TableDataView(display_fields=["first_name"]),
        )
        token = RequestToken(
            dataviews={self.CustomerModel: layout},
            detail_views={self.CustomerModel: detail_view_token} if detail_view_token is not None else {},
        )
        action = call_dataview_action(
            "open-customers",
            self.CustomerModel,
            "Open customers",
            target=target,
            request_token=token,
            filters=[Filter(connector="AND", conditions=[
                FilterCondition(field_path="first_name", lookup_id="equals", value="First Name 3"),
            ])],
        )
        request = self.authenticated_context_request(self.admin_user)
        markup = render_object_action(action, self.CustomerModel.objects.first(), request)
        button = BeautifulSoup(markup, "html.parser").select_one("button[hx-get]")
        self.assertIsNotNone(button)
        if target == "main":
            self.assertEqual(button["hx-target"], "#main-content")
            self.assertEqual(button["hx-push-url"], "true")
        else:
            self.assertEqual(button[f"bloomerp-open-{target}"], f"bloomerp-general-use-{target}")
            self.assertEqual(button["hx-target"], f"#bloomerp-general-use-{target}-body")
            self.assertEqual(button["hx-push-url"], "false")
        scenario.query_params = dict(parse_qsl(urlsplit(button["hx-get"]).query))
        self.assertFalse(REQUEST_TOKEN_QUERY_KEYS.intersection(scenario.query_params))
        scenario.headers = {**(scenario.headers or {}), **json.loads(button["hx-headers"])}

    def renders_action_context(self, response: HttpResponse) -> bool:
        """Make the opening header visible to later row navigation."""
        self.assertEqual(response.context["dataview_request_context_id"], response.wsgi_request.headers[REQUEST_TOKEN_HEADER])
        return True

    def prepare_cached_signed_layouts(self, scenario: RequestScenario) -> None:
        """Store a legacy context whose unrelated detail override has an older expiry."""
        context = RequestToken()
        payload = context.serialize()
        model_label = self.CustomerModel._meta.label_lower
        audience = str(self.admin_user.pk)
        payload["dataviews"] = {model_label: signing.dumps({
            "model_label": model_label,
            "audience": audience,
            "expiry": context.expiry.isoformat(),
            "dataview": TableDataView(display_fields=["first_name"]).model_dump(mode="json"),
        }, salt="bloomerp.tokens.dataview.v1")}
        payload["detail_views"] = {Todo._meta.label_lower: signing.dumps({
            "model_label": Todo._meta.label_lower,
            "audience": audience,
            "expiry": (timezone.now() - timedelta(minutes=1)).isoformat(),
            "tab_configuration": {"tabs": []},
        }, salt="bloomerp.tokens.detail_view.v1")}
        with patch.object(RequestToken, "serialize", return_value=payload):
            scenario.headers = self.request_context_headers(context, self.admin_user)

    def prepare_scoped_access(self, scenario: RequestScenario) -> None:
        """Grant only the requested row and field through the request context."""
        self.set_view_type(TableDataView(display_fields=["age"]))(scenario)
        rule = AccessRule(
            row_permissions=[RowPolicyRuleContent(
                permissions=[BloomerpPermission.VIEW],
                conditions=[FilterCondition(field_path="age", lookup_id="equals", value=5)],
            )],
            field_permissions={"age": [BloomerpPermission.VIEW]},
        )
        scenario.headers = self.request_context_headers(
            RequestToken(policies={self.CustomerModel: rule}), self.normal_user,
        )

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Exercise rendering, filtering, and permission-aware field choices."""
        for i in range(10):
            planet = self.PlanetModel.objects.create(name=f"Planet {i}")
            country = self.CountryModel.objects.create(name=f"Country {i}", planet=planet)
            self.CustomerModel.objects.create(
                first_name=f"First Name {i}", last_name=f"Last Name {i}",
                age=i, country=country,
            )

        kwargs = {"content_type_id": self.get_content_type_for_model(self.CustomerModel).pk}
        customers = self.CustomerModel.objects
        action_rows = self.contains_entries(customers.filter(age=3), ["first_name"])
        detail_view_token = DetailViewToken(
            field_layout=FieldLayout(rows=[LayoutRow(columns=1, items=[LayoutItem(id="first_name")])]),
        )
        overlay_targets: tuple[ObjectActionTarget, ...] = ("modal", "drawer")
        target_scenarios = [
            RequestScenario(
                name=f"A Data View action loads the same filtered rows in the {target}",
                user=self.admin_user,
                view_kwargs=kwargs,
                headers={"HX-Request": "true", "HX-Target": f"bloomerp-general-use-{target}-body"},
                prepare=partial(self.prepare_dataview_action, target=target),
                expected=ExpectedResult(response_validators=[
                    action_rows, self.does_not_contain_text('id="htmx-addendum"'),
                ]),
            )
            for target in overlay_targets
        ]
        target_scenarios.append(RequestScenario(
            name="A Dataview action forwards its signed row layout to the container",
            user=self.admin_user,
            view_kwargs=kwargs,
            headers={"HX-Request": "true", "HX-Target": "bloomerp-general-use-drawer-body"},
            prepare=partial(self.prepare_dataview_action, target="drawer", detail_view_token=detail_view_token),
            expected=ExpectedResult(response_validators=[action_rows, self.renders_action_context]),
        ))
        target_scenarios.append(RequestScenario(
            name="A cached request context uses its own expiry for all of its layouts",
            user=self.admin_user,
            view_kwargs=kwargs,
            prepare=self.prepare_cached_signed_layouts,
            expected=ExpectedResult(response_validators=self.contains_entries(customers.all(), ["first_name"])),
        ))

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
            *target_scenarios,
            RequestScenario(
                name="Main Data View action renders the filtered records and navigation",
                user=self.admin_user,
                view_kwargs=kwargs,
                headers={"HX-Request": "true", "HX-Target": "main-content"},
                prepare=partial(self.prepare_dataview_action, target="main"),
                expected=ExpectedResult(response_validators=[
                    action_rows, self.contains_text('id="htmx-addendum"'),
                    self.contains_text('data-sync-url="true"'),
                ]),
            ),
            RequestScenario(
                name="Reloading a main Data View restores the app shell and filtered records",
                user=self.admin_user,
                view_kwargs=kwargs,
                prepare=partial(self.prepare_dataview_action, target="main"),
                expected=ExpectedResult(response_validators=[
                    action_rows, self.contains_text('id="main-content"'),
                ]),
            ),
            RequestScenario(
                name="Default Contact uses row-specific access even when the field is outside the table columns",
                user=self.normal_user,
                prepare=self.prepare_contact_rows,
                expected=ExpectedResult(response_validators=[
                    self.contains_text("contact-private"),
                    self.contains_text("contact-empty"),
                    self.contains_text("visible-contact@example.com"),
                    self.does_not_contain_text("private-contact@example.com"),
                    self.contains_text('hx-target="#bloomerp-general-use-modal-body"'),
                    self.does_not_contain_text("data-detail-sidebar-view"),
                    self.does_not_contain_text('bloomerp-open-modal="detail-todo-modal"'),
                    self.renders_only_one_contact_menu,
                ]),
            ),
            RequestScenario(
                name="Default actions put Create Todo and Contact in the same dataview menu",
                user=self.normal_user,
                prepare=self.prepare_contact_with_todo_permission,
                expected=ExpectedResult(response_validators=self.groups_create_todo_and_contact),
            ),
            RequestScenario(
                name="RENDERING: Application field overrides ordinary numeric rendering",
                user=self.admin_user,
                view_kwargs=kwargs,
                prepare=self.set_advanced_rendering(
                    "age", '<span class="custom-age">{% if value == 0 %}New{% else %}{{ value }}{% endif %}</span>',
                ),
                expected=ExpectedResult(response_validators=[
                    self.contains_text('<span class="custom-age">New</span>'),
                    self.contains_text('<span class="custom-age">9</span>'),
                    self.contains_text('data-value="0"'),
                ]),
            ),
            RequestScenario(
                name="RENDERING: Custom markup retains Django autoescaping",
                user=self.admin_user,
                view_kwargs=kwargs,
                prepare=self.prepare_escaped_advanced_rendering,
                expected=ExpectedResult(response_validators=[
                    self.contains_text('<strong class="custom-name">&lt;script&gt;unsafe&lt;/script&gt;</strong>'),
                    self.does_not_contain_text('<script>unsafe</script>'),
                ]),
            ),
            RequestScenario(
                name="RENDERING: Invalid legacy template falls back to ordinary rendering",
                user=self.admin_user,
                view_kwargs=kwargs,
                prepare=self.set_advanced_rendering("first_name", "{% if value %}"),
                expected=ExpectedResult(response_validators=[
                    self.contains_text("First Name 0"),
                    self.contains_text("First Name 9"),
                ]),
            ),
            RequestScenario(
                name="FILTERS: Hide applied filters without hiding the filter button or changing results",
                user=self.admin_user,
                view_kwargs=kwargs,
                query_params={
                    **filter_query_params(Filter(connector="AND", conditions=[
                        FilterCondition(field_path="age", lookup_id="equals", value=3),
                    ])),
                    "_arg_hide_filters": "true",
                },
                expected=ExpectedResult(response_validators=[
                    self.contains_entries(customers.filter(age=3)),
                    self.does_not_contain_text("data-rendered-filters"),
                    self.contains_text('data-data-view-button="filter"'),
                ]),
            ),
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
            ),
            RequestScenario(
                name="Access token provides temporary access",
                user=self.normal_user,
                view_kwargs=kwargs,
                prepare=self.prepare_scoped_access,
            expected=ExpectedResult(
                status_code=200,
                response_validators=[
                    self.contains_entries(
                        customers.filter(
                            age=5
                        ),
                        fields=["age"]
                    )
                ]
            )
            ),

        ]

        request_scenarios.extend(
            [
                RequestScenario(
                    name="Avatar is selectable without being a default visible column",
                    user=self.admin_user,
                    view_kwargs=kwargs,
                    expected=ExpectedResult(
                        response_validators=self.avatar_available_but_not_selected
                    ),
                ),
                RequestScenario(
                    name="Avatar is omitted when the viewer lacks avatar field permission",
                    user=self.normal_user,
                    view_kwargs=kwargs,
                    prepare=self.grant_view_without_avatar,
                    expected=ExpectedResult(
                        response_validators=self.avatar_unavailable
                    ),
                ),
                RequestScenario(
                    name="Models without avatar do not gain an avatar choice",
                    user=self.admin_user,
                    view_kwargs={
                        "content_type_id": ContentType.objects.get_for_model(
                            Initiative
                        ).pk
                    },
                    expected=ExpectedResult(
                        response_validators=self.avatar_unavailable
                    ),
                ),
            ]
        )
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

    def avatar_available_but_not_selected(self, response: HttpResponse) -> bool:
        """Keep avatar discoverable in display options without adding it by default."""
        fields = response.context["fields"]
        avatar_choices = [
            (field, selected)
            for field, selected in fields.accessible_fields
            if field.field == "avatar"
        ]
        return (
            len(avatar_choices) == 1
            and not avatar_choices[0][1]
            and response.context["avatar_field"] is None
        )

    def avatar_unavailable(self, response: HttpResponse) -> bool:
        """Do not expose an unsupported or permission-denied avatar field."""
        return all(
            field.field != "avatar"
            for field, _selected in response.context["fields"].accessible_fields
        )

    def grant_view_without_avatar(self, _scenario: RequestScenario) -> None:
        """Give access to customer rows and one business field, but not avatars."""
        field = ApplicationField.get_by_field(self.CustomerModel, "first_name")
        PolicyManager.create_policy(
            self.CustomerModel,
            field_permissions={field: [BloomerpPermission.VIEW]},
            global_permissions=[BloomerpPermission.VIEW],
            row_permissions=[
                RowPolicyRuleContent(
                    connector="AND",
                    permissions=[BloomerpPermission.VIEW],
                    conditions=[],
                )
            ],
        ).assign_user(self.normal_user)

