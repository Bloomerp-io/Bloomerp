from unittest.mock import patch

from bs4 import BeautifulSoup
from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.auth.models import Permission

from bloomerp.models import (
    ApplicationField,
    ContentType,
    FieldPolicy,
    Policy,
    RowPolicy,
    RowPolicyRule,
)
from bloomerp.models.audit.activity_log import ActivityLog, ActivityLogAction
from bloomerp.modules.definition import ModuleConfig
from bloomerp.router import BloomerpRoute, RouteType, ViewType
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestGlobalSearchComponent(BloomerpComponentTestCase):
    """Tests function `global_search` from `bloomerp/components/search/global_search.py`."""

    auto_create_customers = False
    view_name = "components_global_search"

    def get_test_scenarios(self) -> list[RequestScenario]:
        return [
            RequestScenario(
                name="returns a successful response",
                user=self.admin_user,
                query_params={"q": "John"},
            ),
            RequestScenario(
                name="route search uses active-language metadata",
                user=self.admin_user,
                query_params={"q": ">clientes"},
                prepare=self._prepare_localized_route_search,
                cleanup=self._stop_patches,
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text("Clientes"),
                        self.contains_text("Consultar clientes."),
                    ]
                ),
            ),
            RequestScenario(
                name="module search resolves a localized module name",
                user=self.admin_user,
                query_params={"q": "/utilizadores//Grenit"},
                prepare=self._prepare_localized_module_search,
                cleanup=self._stop_patches,
                expected=ExpectedResult(response_validators=self.contains_text("Utilizadores")),
            ),
            RequestScenario(
                name="admin general search returns only matching customers",
                user=self.admin_user,
                query_params={"q": "Grenit Xhaka"},
                prepare=self._create_matching_and_non_matching_customers,
                expected=ExpectedResult(response_validators=self._matching_customer_only),
            ),
            RequestScenario(
                name="user without permissions receives no general-search results",
                user=self.normal_user,
                query_params={"q": "Grenit Xhaka"},
                prepare=self._create_matching_and_non_matching_customers,
                expected=ExpectedResult(
                    response_validators=[
                        self.response_text_contains("No results found."),
                        self._non_matching_customer_is_absent,
                    ]
                ),
            ),
            RequestScenario(
                name="activity logs are excluded from global search",
                user=self.admin_user,
                query_params={"q": "activity-log-global-search-target"},
                prepare=self._create_activity_log,
                expected=ExpectedResult(
                    response_validators=[
                        self.response_text_contains("No results found."),
                        self.response_text_does_not_contain("Activity Logs"),
                    ]
                ),
            ),
            RequestScenario(
                name="Django admin log entries are excluded from global search",
                user=self.admin_user,
                query_params={"q": "admin-log-global-search-target"},
                prepare=self._create_django_admin_log_entry,
                expected=ExpectedResult(
                    response_validators=[
                        self.response_text_contains("No results found."),
                        self.response_text_does_not_contain("Log Entries"),
                    ]
                ),
            ),
            RequestScenario(
                name="user with matching row and field policies sees matching customers",
                user=self.normal_user,
                query_params={"q": "Grenit Xhaka"},
                prepare=self._prepare_policy_scoped_customer_search,
                expected=ExpectedResult(response_validators=self._matching_customer_only),
            ),
            RequestScenario(
                name="module and model search returns matching customers",
                user=self.admin_user,
                query_params={"q": "/misc/customer/Grenit"},
                prepare=self._create_matching_customer,
                expected=ExpectedResult(response_validators=self._matching_customer_is_present),
            ),
            RequestScenario(
                name="module search with an invalid model returns no matching customers",
                user=self.admin_user,
                query_params={"q": "/misc/invalidmodel/Grenit"},
                prepare=self._create_matching_customer,
                expected=ExpectedResult(response_validators=self._matching_customer_is_absent),
            ),
            RequestScenario(
                name="module search with an invalid module returns no matching customers",
                user=self.admin_user,
                query_params={"q": "/whatever/invalidmodel/Grenit"},
                prepare=self._create_matching_customer,
                expected=ExpectedResult(response_validators=self._matching_customer_is_absent),
            ),
            RequestScenario(
                name="module search accepts a partial module name",
                user=self.admin_user,
                query_params={"q": "/mi/customer/Grenit"},
                prepare=self._create_matching_customer,
                expected=ExpectedResult(response_validators=self._matching_customer_is_present),
            ),
            RequestScenario(
                name="module search accepts a partial model name",
                user=self.admin_user,
                query_params={"q": "/misc/cust/Grenit"},
                prepare=self._create_matching_customer,
                expected=ExpectedResult(response_validators=self._matching_customer_is_present),
            ),
            RequestScenario(
                name="module search accepts partial module and model names",
                user=self.admin_user,
                query_params={"q": "/mi/cust/Grenit"},
                prepare=self._create_matching_customer,
                expected=ExpectedResult(response_validators=self._matching_customer_is_present),
            ),
            RequestScenario(
                name="module and model search returns no result for an unmatched query",
                user=self.admin_user,
                query_params={"q": "/misc/customer/Nonexistent"},
                prepare=self._create_matching_customer,
                expected=ExpectedResult(response_validators=self._matching_customer_is_absent),
            ),
            RequestScenario(
                name="model search without a module returns matching customers",
                user=self.admin_user,
                query_params={"q": "//customer/Grenit"},
                prepare=self._create_matching_customer,
                expected=ExpectedResult(response_validators=self._matching_customer_is_present),
            ),
            RequestScenario(
                name="three slashes perform a general search",
                user=self.admin_user,
                query_params={"q": "///Grenit"},
                prepare=self._create_matching_customer,
                expected=ExpectedResult(response_validators=self._matching_customer_is_present),
            ),
            RequestScenario(
                name="module and model search accepts a full query",
                user=self.admin_user,
                query_params={"q": "/misc/customer/Grenit Xhaka"},
                prepare=self._create_matching_customer,
                expected=ExpectedResult(response_validators=self._matching_customer_is_present),
            ),
        ]

    def _prepare_localized_route_search(self, _scenario: RequestScenario) -> None:
        route = BloomerpRoute(
            path="/customers/",
            route_type=RouteType.APP,
            name="Customers",
            url_name="bloomerp_home_view",
            view_type=ViewType.FUNCTION,
            view=lambda request: None,
            description="Browse customers.",
            name_message="Customers",
            description_message="Browse customers.",
            owner_app_label="sales",
        )
        self._start_patch(
            "bloomerp.components.search.global_search.router.get_routes",
            return_value=[route],
        )
        self._start_patch(
            "bloomerp.router.pgettext",
            side_effect=lambda _context, message: {
                "Customers": "Clientes",
                "Browse customers.": "Consultar clientes.",
            }.get(message, message),
        )

    def _prepare_localized_module_search(self, _scenario: RequestScenario) -> None:
        module = ModuleConfig(
            id="users",
            code="users",
            name="Users",
            owner_app_label="bloomerp",
        )
        self._start_patch(
            "bloomerp.components.search.global_search._ensure_module_registry_models"
        )
        self._start_patch(
            "bloomerp.components.search.global_search.module_registry.get",
            return_value=None,
        )
        self._start_patch(
            "bloomerp.components.search.global_search.module_registry.get_all",
            return_value={"users": module},
        )
        self._start_patch(
            "bloomerp.components.search.global_search.module_registry.get_models_for_module",
            return_value=[],
        )
        self._start_patch(
            "bloomerp.modules.definition.pgettext",
            side_effect=lambda _context, message: "Utilizadores"
            if message == "Users"
            else message,
        )

    def _create_matching_customer(self, _scenario: RequestScenario) -> None:
        self._matching_customer = self.create_customer("Grenit", "Xhaka", 30)

    def _create_matching_and_non_matching_customers(
        self, scenario: RequestScenario
    ) -> None:
        self._create_matching_customer(scenario)
        self._non_matching_customer = self.create_customer("Jane", "Smith", 25)

    def _prepare_policy_scoped_customer_search(self, scenario: RequestScenario) -> None:
        self._create_matching_and_non_matching_customers(scenario)
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        application_field = ApplicationField.get_for_model(self.CustomerModel).get(
            field="first_name"
        )
        permissions = Permission.objects.filter(content_type=content_type)
        field_policy = FieldPolicy.objects.create(
            content_type=content_type,
            name="field policy",
            rule={str(application_field.id): [permissions.first().codename]},
        )
        row_policy = RowPolicy.objects.create(
            content_type=content_type,
            name="row policy",
        )
        row_policy_rule = RowPolicyRule.objects.create(
            row_policy=row_policy,
            rule={
                "connector": "OR",
                "conditions": [
                    {
                        "application_field_id": application_field.id,
                        "value": "Grenit",
                        "operator": "equals",
                    }
                ],
            },
        )
        row_policy_rule.permissions.set(permissions)
        policy = Policy.objects.create(
            name="Test Policy",
            row_policy=row_policy,
            field_policy=field_policy,
        )
        policy.assign_user(self.normal_user)

    def _create_activity_log(self, _scenario: RequestScenario) -> None:
        content_type = ContentType.objects.get_for_model(ActivityLog)
        permission = Permission.objects.get(
            content_type=content_type,
            codename="view_activitylog",
        )
        self.admin_user.user_permissions.add(permission)
        ActivityLog.objects.create(
            actor=self.admin_user,
            content_type=ContentType.objects.get_for_model(self.CustomerModel),
            object_id="activity-log-global-search-target",
            action=ActivityLogAction.CHANGE,
        )

    def _create_django_admin_log_entry(self, _scenario: RequestScenario) -> None:
        content_type = ContentType.objects.get_for_model(LogEntry)
        permission = Permission.objects.get(
            content_type=content_type,
            codename="view_logentry",
        )
        self.admin_user.user_permissions.add(permission)
        LogEntry.objects.create(
            user=self.admin_user,
            content_type=ContentType.objects.get_for_model(self.CustomerModel),
            object_id="admin-log-global-search-target",
            object_repr="admin-log-global-search-target",
            action_flag=ADDITION,
            change_message="admin-log-global-search-target",
        )

    def _start_patch(self, target: str, **kwargs) -> None:
        patcher = patch(target, **kwargs)
        patcher.start()
        self._patchers = getattr(self, "_patchers", []) + [patcher]

    def _stop_patches(self, _scenario: RequestScenario) -> None:
        for patcher in reversed(getattr(self, "_patchers", [])):
            patcher.stop()
        self._patchers = []

    def _matching_customer_only(self, response) -> bool:
        return self._matching_customer_is_present(response) and self._non_matching_customer_is_absent(response)

    def _matching_customer_is_present(self, response) -> bool:
        return str(self._matching_customer) in self._response_text(response)

    def _matching_customer_is_absent(self, response) -> bool:
        return str(self._matching_customer) not in self._response_text(response)

    def _non_matching_customer_is_absent(self, response) -> bool:
        return str(self._non_matching_customer) not in self._response_text(response)

    @classmethod
    def response_text_contains(cls, value: str):
        return cls._named_validator(
            f"response_text_contains({value!r})",
            lambda response: value in cls._response_text(response),
        )

    @classmethod
    def response_text_does_not_contain(cls, value: str):
        return cls._named_validator(
            f"response_text_does_not_contain({value!r})",
            lambda response: value not in cls._response_text(response),
        )

    @staticmethod
    def _response_text(response) -> str:
        return BeautifulSoup(
            response.content.decode(response.charset or "utf-8"), "html.parser"
        ).get_text()
