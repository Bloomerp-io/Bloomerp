import json
from unittest.mock import patch

from bs4 import BeautifulSoup
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import clear_url_caches, path, reverse

from bloomerp.filters.definition import FilterCondition
from bloomerp.lookups import builtins as lookups
from bloomerp.management.commands import save_application_fields
from bloomerp.models import ApplicationField, FieldPolicy, Policy, RowPolicy, RowPolicyRule
from bloomerp.models.project_management.todo import Todo, TodoPriority, TodoStatus
from bloomerp.models.project_management.todo_label import TodoLabel
from bloomerp.models.users.user_object_layout_preference import UserObjectLayoutPreference
from bloomerp.models.workspaces.sidebar import Sidebar
from bloomerp.permissions.definition import AccessRule, BloomerpPermission, RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.router import router
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.tests.base.request_test_case_mixin import ExpectedResult
from bloomerp.tests.base.view_test_case import BloomerpModelViewTestCase, ModelRequestScenario, RequestScenario
from bloomerp.views.generic.model.create import BloomerpCreateView
from config.urls import urlpatterns as project_urlpatterns


urlpatterns = list(project_urlpatterns)


def overridden_create_view(_request, *args, **kwargs):
    return HttpResponse("overridden")


@override_settings(ROOT_URLCONF=__name__)
class TestBloomerpCreateView(BloomerpModelViewTestCase):
    """Readable behavior contract for generated create views and their modal."""

    view_name = "add"
    model = None
    create_foreign_models = True
    auto_create_customers = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model = cls.CustomerModel
        for route_name, model in (
            ("test_customer_create", cls.CustomerModel),
            ("test_planet_create", cls.PlanetModel),
            ("test_todo_create", Todo),
        ):
            urlpatterns.append(
                path(
                    f"test/{route_name}/",
                    BloomerpCreateView.as_view(model=model),
                    name=route_name,
                )
            )
        clear_url_caches()

    @classmethod
    def tearDownClass(cls):
        del urlpatterns[-3:]
        clear_url_caches()
        super().tearDownClass()

    def extendedSetup(self):
        self.content_type = ContentType.objects.get_for_model(self.CustomerModel)
        self._ensure_permissions_for_model(self.CustomerModel)
        self.fields_by_name = {
            field.field: field
            for field in ApplicationField.get_for_model(self.CustomerModel)
        }

    def get_test_scenarios(self) -> list[RequestScenario]:
        customer = self.CustomerModel
        planet = self.PlanetModel
        return [
            ModelRequestScenario(
                name="Query parameters prefill create fields",
                description="UC: A user follows a create URL containing field values.\nExpected Result: Matching form inputs are prefilled.",
                model=customer, user=self.admin_user, query_params={"first_name": "XYZ"},
                expected=ExpectedResult(response_validators=self.input_equals("first_name", "XYZ")),
            ),
            ModelRequestScenario(
                name="Generated create layout omits system fields and keeps files enabled",
                description="UC: An administrator opens a generated create form.\nExpected Result: Internal system fields are omitted while files remain editable.",
                model=customer, user=self.admin_user,
                expected=ExpectedResult(response_validators=self.generated_create_field_state),
            ),
            ModelRequestScenario(
                name="Shared initial create layout is materialized and selected",
                description="UC: A shared layout is marked as the user's initial default.\nExpected Result: It renders through a selected live reference without a local duplicate.",
                model=customer, user=self.admin_user, prepare=self.prepare_shared_layout,
                expected=ExpectedResult(response_validators=[self.contains_text("Shared create layout"), self.shared_layout_reference_selected]),
            ),
            ModelRequestScenario(
                name="One-to-many values survive a validation error",
                description="UC: Related rows are submitted while the parent required name is missing.\nExpected Result: The invalid form re-renders both submitted row values.",
                model=planet, method="POST", user=self.admin_user,
                data={"countries__0__name": "Testland", "countries__1__name": "Examplestan"},
                expected=ExpectedResult(response_validators=[self.input_equals("countries__0__name", "Testland"), self.input_equals("countries__1__name", "Examplestan")]),
            ),
            ModelRequestScenario(
                name="One-to-many query values prefill every row",
                description="UC: A create link supplies two related rows.\nExpected Result: Both nested inputs retain their values.",
                model=planet, user=self.admin_user,
                query_params={"countries__0__name": "Testland", "countries__1__name": "Examplestan"},
                expected=ExpectedResult(response_validators=[self.input_equals("countries__0__name", "Testland"), self.input_equals("countries__1__name", "Examplestan")]),
            ),
            ModelRequestScenario(
                name="Create form exposes save and save-and-create-next controls",
                description="UC: A user opens a create form.\nExpected Result: Both submit controls and a safe next target are rendered.",
                model=customer, user=self.admin_user,
                expected=ExpectedResult(response_validators=self.save_controls_render),
            ),
            ModelRequestScenario(
                name="Save-and-create-next persists and returns to create",
                description="UC: A user submits valid data with the current create URL as next.\nExpected Result: The object is created and the response redirects back to create.",
                model=customer, method="POST", user=self.admin_user,
                data={"first_name": "Another", "last_name": "Customer", "age": 30, "next": "/test/test_customer_create/"},
                expected=ExpectedResult(status_code=302, response_validators=self.saved_customer_and_redirected),
            ),
            ModelRequestScenario(
                name="Todo creation does not require a content object outside its layout",
                description="UC: An administrator creates a Todo whose layout omits content_object.\nExpected Result: The Todo is created without requiring a related object.",
                model=Todo, method="POST", user=self.admin_user,
                data={
                    "title": "Standalone todo",
                    "priority": TodoPriority.MEDIUM,
                    "status": TodoStatus.BACKLOG,
                },
                expected=ExpectedResult(status_code=302, response_validators=self.standalone_todo_created),
            ),
            ModelRequestScenario(
                name="Create page requires global add permission",
                description="UC: A regular user has no add permission.\nExpected Result: The create page returns 403.",
                model=customer, user=self.normal_user,
                expected=ExpectedResult(status_code=403),
            ),
            ModelRequestScenario(
                name="Missing required field permissions block creation",
                description="UC: Add access omits a required field.\nExpected Result: The form explains which required access is missing.",
                model=customer, user=self.normal_user, prepare=self.grant_missing_required_policy,
                expected=ExpectedResult(response_validators=self.contains_text("do not have access to the required fields")),
            ),
            ModelRequestScenario(
                name="Missing add row policy blocks creation",
                description="UC: Fields are addable but no add row rule applies.\nExpected Result: The form explains that no create row policy applies.",
                model=customer, user=self.normal_user, prepare=self.grant_no_row_policy,
                expected=ExpectedResult(response_validators=self.contains_text("no create row policy applies")),
            ),
            ModelRequestScenario(
                name="Create form renders only addable fields",
                description="UC: A user may add name and age but not country.\nExpected Result: Permitted fields are visible and country is hidden.",
                model=customer, user=self.normal_user, prepare=self.grant_basic_create_policy,
                expected=ExpectedResult(response_validators=self.only_addable_fields_render),
            ),
            ModelRequestScenario(
                name="Injected non-addable field is rejected",
                description="UC: A user injects country into a permitted create request.\nExpected Result: The field is rejected and no customer is created.",
                model=customer, method="POST", user=self.normal_user, prepare=self.prepare_injected_country,
                data={"first_name": "Allowed", "last_name": "Person", "age": 30},
                expected=ExpectedResult(response_validators=[self.contains_text("Permission denied for fields: country"), self.no_customer_created]),
            ),
            ModelRequestScenario(
                name="Values outside add row policy are rejected",
                description="UC: Submitted values do not satisfy the add row rule.\nExpected Result: A policy error renders and no object is created.",
                model=customer, method="POST", user=self.normal_user, prepare=self.grant_basic_create_policy,
                data={"first_name": "Blocked", "last_name": "Person", "age": 30},
                expected=ExpectedResult(response_validators=[self.contains_text("do not have permission to create an object with these values"), self.no_customer_created]),
            ),
            ModelRequestScenario(
                name="Field validation error appears in its layout item",
                description="UC: A user submits nonnumeric age.\nExpected Result: The age layout item shows an error style.",
                model=customer, method="POST", user=self.normal_user, prepare=self.grant_basic_create_policy,
                data={"first_name": "Allowed", "last_name": "Person", "age": "not-a-number"},
                expected=ExpectedResult(response_validators=self.age_error_visible),
            ),
            ModelRequestScenario(
                name="Hidden required field produces a visible form error",
                description="UC: A required field is absent from the selected layout and POST.\nExpected Result: Its validation message remains visible and creation is atomic.",
                model=customer, method="POST", user=self.normal_user, prepare=self.prepare_hidden_required_layout,
                data={"first_name": "Allowed", "age": 30},
                expected=ExpectedResult(response_validators=[self.hidden_required_error_visible, self.no_customer_created]),
            ),
            ModelRequestScenario(
                name="Matching add permissions and row policy create an attributed object",
                description="UC: Submitted values satisfy field and row policy.\nExpected Result: Creation succeeds and records the authenticated creator.",
                model=customer, method="POST", user=self.normal_user, prepare=self.grant_basic_create_policy,
                data={"first_name": "Allowed", "last_name": "Person", "age": 30},
                expected=ExpectedResult(status_code=302, response_validators=self.allowed_customer_created),
            ),
            ModelRequestScenario(
                name="AND add rule matches a foreign-key value",
                description="UC: An AND row rule contains text and foreign-key conditions.\nExpected Result: A matching object is created with that relation.",
                model=customer, method="POST", user=self.normal_user, prepare=self.prepare_foreign_key_policy,
                data={"first_name": "Jaimy", "last_name": "Peeters", "age": 30},
                expected=ExpectedResult(status_code=302, response_validators=self.foreign_customer_created),
            ),
            RequestScenario(
                name="Modal redirects to an overridden full create view",
                description="UC: A model overrides its generated create route.\nExpected Result: Opening the modal responds with HX-Redirect to that route.",
                view_name="todo_label_component", user=self.admin_user, headers={"hx-request": "true"},
                prepare=self.override_customer_create_route, cleanup=self.restore_customer_create_route,
                expected=ExpectedResult(response_validators=self.component_override_redirected),
            ),
            RequestScenario(
                name="Create available-items endpoint respects field permissions",
                description="UC: A layout editor requests create fields.\nExpected Result: Addable names are returned and country is omitted.",
                view_name="available_create_items", user=self.normal_user, prepare=self.grant_basic_create_policy,
                query_params={}, expected=ExpectedResult(response_validators=self.available_items_are_permission_scoped),
            ),
            RequestScenario(
                name="Create layout can remove a permitted system field",
                description="UC: An administrator removes an item from a create layout.\nExpected Result: The saved layout preserves that removal.",
                view_name="save_create_layout", method="POST", user=self.admin_user, content_type="application/json", prepare=self.prepare_layout_without_id,
                expected=ExpectedResult(response_validators=self.id_removal_persisted),
            ),
            RequestScenario(
                name="Create layout save persists row shape",
                description="UC: A user saves a custom create row.\nExpected Result: Its title, columns, item and colspan persist.",
                view_name="save_create_layout", method="POST", user=self.admin_user, content_type="application/json", prepare=self.prepare_custom_layout_save,
                expected=ExpectedResult(response_validators=self.custom_layout_persisted),
            ),
            ModelRequestScenario(
                name="Empty selected layout is repaired before create renders",
                description="UC: A selected create preference contains an empty layout.\nExpected Result: Opening create repairs it with default items.",
                model=customer, user=self.normal_user, prepare=self.prepare_empty_layout,
                expected=ExpectedResult(response_validators=self.empty_layout_was_repaired),
            ),
            ModelRequestScenario(
                name="Selecting a layout unselects the previous layout",
                description="UC: A second layout is selected for the same user and model.\nExpected Result: Exactly the second preference remains selected.",
                model=customer, user=self.admin_user, prepare=self.prepare_two_layouts,
                expected=ExpectedResult(response_validators=self.only_second_layout_selected),
            ),
            ModelRequestScenario(
                name="Create with user acount equals to",
                method="POST",
                description="""
                UC: user_account equals to permission should work
                
                """,
                model=customer,
                user=self.normal_user,
                data={
                    "first_name" : "David",
                    "last_name" : "James",
                    "user_account" : str(self.normal_user.pk),
                    "age" : 12
                },
                prepare=lambda _: PolicyManager.create_policy(
                    model_or_content_type=customer,
                    access_rule=AccessRule(
                        row_permissions=[
                            RowPolicyRuleContent(
                                connector="AND",
                                conditions=[
                                    FilterCondition(
                                        field_path="user_account",
                                        value="$user",
                                        lookup_id="equals_user"
                                    )
                                ],
                                permissions=[BloomerpPermission.ADD, BloomerpPermission.VIEW]
                            )
                        ],
                        field_permissions={
                            "first_name" : [BloomerpPermission.ADD, BloomerpPermission.VIEW],
                            "last_name" : [BloomerpPermission.ADD, BloomerpPermission.VIEW],
                            "age" : [BloomerpPermission.ADD, BloomerpPermission.VIEW],
                            "user_account" : [BloomerpPermission.ADD, BloomerpPermission.VIEW],
                        }
                    ),
                    global_permissions=[BloomerpPermission.ADD, BloomerpPermission.VIEW]
                ).assign_user(
                    self.normal_user
                ),
                expected=ExpectedResult(
                    status_code=302,
                    response_validators=[
                        lambda _: customer.objects.filter(
                            first_name="David",
                            last_name="James",
                            age=12
                        ).exists(),
                        
                    ]
                )
                
            )
        ]

    def get_endpoint(self, view_name, kwargs, setup=None):
        if view_name == "add":
            route_name = "test_customer_create"
            if setup.model is self.PlanetModel:
                route_name = "test_planet_create"
            elif setup.model is Todo:
                route_name = "test_todo_create"
            return reverse(route_name)
        if view_name == "customer_component":
            return reverse("components_create_object", kwargs={"content_type_id": self.content_type.pk})
        if view_name == "todo_label_component":
            return reverse("components_create_object", kwargs={"content_type_id": ContentType.objects.get_for_model(TodoLabel).pk})
        if view_name == "available_create_items":
            owner_type = ContentType.objects.get_for_model(UserObjectLayoutPreference)
            return reverse("components_available_layout_items", kwargs={"content_type_id": owner_type.pk}) + f"?layout_mode=create&target_content_type_id={self.content_type.pk}"
        if view_name == "save_create_layout":
            return reverse("components_save_layout_object", kwargs={"content_type_id": ContentType.objects.get_for_model(UserObjectLayoutPreference).pk, "object_id": self.layout_preference.pk}) + f"?layout_mode=create&target_content_type_id={self.content_type.pk}"
        return super().get_endpoint(view_name, kwargs, setup)

    @classmethod
    def input_equals(cls, name, value):
        def validator(response):
            soup = BeautifulSoup(response.content, "html.parser")
            node = soup.find(attrs={"name": name})
            return node is not None and node.get("value") == value
        return cls._named_validator(f"input_equals({name!r}, {value!r})", validator)

    def _ensure_permissions_for_model(self, model):
        content_type = ContentType.objects.get_for_model(model)
        for action in model._meta.default_permissions:
            Permission.objects.get_or_create(codename=f"{action}_{model._meta.model_name}", content_type=content_type, defaults={"name": f"Can {action} {model._meta.verbose_name}"})

    def grant_policy(self, fields, row_rules):
        codename = f"add_{self.CustomerModel._meta.model_name}"
        field_policy = FieldPolicy.objects.create(content_type=self.content_type, name="Create field policy", rule={str(self.fields_by_name[name].pk): [codename] for name in fields})
        row_policy = RowPolicy.objects.create(content_type=self.content_type, name="Create row policy")
        for rule in row_rules:
            row_rule = RowPolicyRule.objects.create(row_policy=row_policy, rule=rule if "conditions" in rule else {"connector": "OR", "conditions": [rule]})
            row_rule.add_permission(codename)
        policy = Policy.objects.create(name="Create policy", row_policy=row_policy, field_policy=field_policy)
        policy.assign_user(self.normal_user)
        permission = Permission.objects.get(content_type=self.content_type, codename=codename)
        self.normal_user.user_permissions.add(permission)
        policy.global_permissions.add(permission)

    def basic_rule(self):
        return {"application_field_id": str(self.fields_by_name["first_name"].pk), "operator": lookups.EQUALS.id, "value": "Allowed"}

    def grant_basic_create_policy(self, _scenario):
        self.grant_policy(["first_name", "last_name", "age"], [self.basic_rule()])

    def grant_missing_required_policy(self, _scenario):
        self.grant_policy(["first_name", "last_name"], [self.basic_rule()])

    def grant_no_row_policy(self, _scenario):
        self.grant_policy(["first_name", "last_name", "age"], [])

    def generated_create_field_state(self, response):
        items = {str(item.id): item for row in response.context["layout"].rows for item in row.items}
        system = {"id", "pk", "datetime_created", "datetime_updated", "created_by", "updated_by", "comments"}
        return all(str(self.fields_by_name[name].pk) not in items for name in system) and items[str(self.fields_by_name["files"].pk)].is_visible and "disabled" not in items[str(self.fields_by_name["files"].pk)].content

    def prepare_shared_layout(self, _scenario):
        self.shared_layout = UserObjectLayoutPreference.objects.create(user=self.normal_user, content_type=self.content_type, name="Shared initial create", initial_default=True, layout={"rows": [{"title": "Shared create layout", "columns": 1, "items": [{"id": self.fields_by_name["first_name"].pk, "colspan": 1}]}]})
        self.shared_layout.shared_with_users.add(self.admin_user)
        UserObjectLayoutPreference.objects.filter(user=self.admin_user, content_type=self.content_type).delete()
        Sidebar.objects.create(user=self.admin_user, name="Test sidebar", selected=True)

    def shared_layout_reference_selected(self, _response):
        reference = UserObjectLayoutPreference.objects.get(user=self.admin_user, content_type=self.content_type)
        return reference.source_object == self.shared_layout and reference.selected and not UserObjectLayoutPreference.objects.filter(user=self.admin_user, content_type=self.content_type, source_object__isnull=True).exists()

    def save_controls_render(self, response):
        html = response.content.decode()
        return all(value in html for value in ('id="object-crud-container-save-button"', 'id="object-crud-container-save-and-create-new-button"', 'name="next"', 'value="/test/test_customer_create/"'))

    def saved_customer_and_redirected(self, response):
        created = self.CustomerModel.objects.get()
        return response.headers.get("Location") == "/test/test_customer_create/" and created.first_name == "Another" and created.last_name == "Customer"

    def standalone_todo_created(self, _response):
        return Todo.objects.filter(
            title="Standalone todo",
            content_type__isnull=True,
            object_id__isnull=True,
        ).exists()

    def only_addable_fields_render(self, response):
        items = {str(item.id): item for row in response.context["layout"].rows for item in row.items}
        return all(items[str(self.fields_by_name[name].pk)].is_visible for name in ("first_name", "last_name", "age")) and not items[str(self.fields_by_name["country"].pk)].is_visible

    def prepare_injected_country(self, scenario):
        self.grant_basic_create_policy(scenario)
        scenario.data["country"] = self.CountryModel.objects.get(name="Belgium").pk

    def no_customer_created(self, _response):
        return not self.CustomerModel.objects.exists()

    def age_error_visible(self, response):
        return f'data-layout-item-id="{self.fields_by_name["age"].pk}"' in response.content.decode() and "border-red-500" in response.content.decode()

    def hidden_required_error_visible(self, response):
        return "This field is required." in response.content.decode()

    def prepare_hidden_required_layout(self, scenario):
        self.grant_basic_create_policy(scenario)
        self.layout_preference = PreferenceManager(self.normal_user).get_or_create_selected(UserObjectLayoutPreference, scope={"content_type_id": self.content_type.pk})
        self.layout_preference.layout = {"rows": [{"title": "Primary", "columns": 2, "items": [{"id": self.fields_by_name["first_name"].pk, "colspan": 1}, {"id": self.fields_by_name["age"].pk, "colspan": 1}]}]}
        self.layout_preference.save(update_fields=["layout"])

    def allowed_customer_created(self, _response):
        created = self.CustomerModel.objects.get()
        return created.first_name == "Allowed" and created.created_by == self.normal_user

    def prepare_foreign_key_policy(self, scenario):
        self.belgium = self.CountryModel.objects.get(name="Belgium")
        self.grant_policy(["first_name", "last_name", "age", "country"], [{"connector": "AND", "conditions": [{"application_field_id": str(self.fields_by_name["last_name"].pk), "operator": lookups.EQUALS.id, "value": "Peeters"}, {"application_field_id": str(self.fields_by_name["country"].pk), "operator": lookups.EQUALS.id, "value": str(self.belgium.pk)}]}])
        scenario.data["country"] = str(self.belgium.pk)

    def foreign_customer_created(self, _response):
        created = self.CustomerModel.objects.get()
        return created.last_name == "Peeters" and created.country == self.belgium

    def foreign_widget_trigger_is_correct(self, response):
        trigger = json.loads(response["HX-Trigger"])
        event = trigger["bloomerp:foreign-field-object-created"]
        label = TodoLabel.objects.get(name="Created From Widget")
        return "HX-Refresh" not in response and event.items() >= {"foreign_field_widget_id": "widget-123", "content_type_id": ContentType.objects.get_for_model(TodoLabel).pk, "object_id": str(label.pk), "object_label": "Created From Widget"}.items()

    def add_component_next(self, scenario):
        self.component_url = reverse("components_create_object", kwargs={"content_type_id": ContentType.objects.get_for_model(TodoLabel).pk})
        scenario.data["next"] = self.component_url

    def component_redirect_is_correct(self, response):
        return response.headers.get("Location") == self.component_url and "HX-Refresh" not in response and TodoLabel.objects.filter(name="Modal label").count() == 1

    def todo_label_created(self, response):
        return response.headers.get("HX-Refresh") == "true" and TodoLabel.objects.filter(name="Backend", color="#000000").exists()

    def override_customer_create_route(self, _scenario):
        self.saved_routes = router.routes.copy()
        self.saved_templates = router._model_route_templates.copy()
        router.register(path="create", route_type="model", name="Create Todo Label Override", url_name="add", models=TodoLabel, override=True)(overridden_create_view)

    def restore_customer_create_route(self, _scenario):
        router.routes = self.saved_routes
        router._model_route_templates = self.saved_templates

    def component_override_redirected(self, response):
        route = next(route for route in router.get_routes_by_model(TodoLabel) if route.base_url_name == "add")
        return response.headers.get("HX-Redirect") == reverse(route.url_name)

    def available_items_are_permission_scoped(self, response):
        html = response.content.decode()
        return self.fields_by_name["first_name"].title in html and self.fields_by_name["country"].title not in html

    def prepare_layout_without_id(self, scenario):
        self.layout_preference = PreferenceManager(self.admin_user).get_or_create_selected(UserObjectLayoutPreference, scope={"content_type_id": self.content_type.pk})
        layout = self.layout_preference.layout_obj.model_copy(deep=True)
        self.removed_id = self.fields_by_name["id"].pk
        for row in layout.rows:
            row.items = [item for item in row.items if item.id != self.removed_id]
        scenario.data = json.dumps({"target_content_type_id": self.content_type.pk, "layout": layout.model_dump()})

    def id_removal_persisted(self, _response):
        self.layout_preference.refresh_from_db()
        return self.removed_id not in {item.id for row in self.layout_preference.layout_obj.rows for item in row.items}

    def prepare_custom_layout_save(self, scenario):
        self.layout_preference = PreferenceManager(self.admin_user).get_or_create_selected(UserObjectLayoutPreference, scope={"content_type_id": self.content_type.pk})
        self.custom_field = self.fields_by_name["first_name"]
        scenario.data = json.dumps({"layout": {"rows": [{"title": "custom-shape", "columns": 3, "items": [{"id": self.custom_field.pk, "colspan": 2}]}]}})

    def custom_layout_persisted(self, _response):
        self.layout_preference.refresh_from_db()
        row = self.layout_preference.layout_obj.rows[0]
        return row.title == "custom-shape" and row.columns == 3 and row.items[0].id == str(self.custom_field.pk) and row.items[0].colspan == 2

    def prepare_empty_layout(self, scenario):
        self.grant_basic_create_policy(scenario)
        self.layout_preference = UserObjectLayoutPreference.objects.create(user=self.normal_user, content_type=self.content_type, layout={}, selected=True)

    def empty_layout_was_repaired(self, _response):
        self.layout_preference.refresh_from_db()
        return any(row.items for row in self.layout_preference.layout_obj.rows)

    def prepare_two_layouts(self, _scenario):
        self.first_layout = UserObjectLayoutPreference.objects.create(user=self.admin_user, content_type=self.content_type, layout={})
        self.second_layout = UserObjectLayoutPreference.objects.create(user=self.admin_user, content_type=self.content_type, layout={}, selected=True)

    def only_second_layout_selected(self, _response):
        self.first_layout.refresh_from_db()
        self.second_layout.refresh_from_db()
        return not self.first_layout.selected and self.second_layout.selected

