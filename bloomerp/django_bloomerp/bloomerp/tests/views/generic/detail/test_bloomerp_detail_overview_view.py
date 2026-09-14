from bs4 import BeautifulSoup
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import override_settings
from django.urls import clear_url_caches, path, reverse

from bloomerp.lookups import builtins as lookups
from bloomerp.models import ApplicationField, FieldPolicy, Policy, RowPolicy, RowPolicyRule
from bloomerp.models.audit.activity_log import ActivityLog, ActivityLogAction, ActivityLogSource
from bloomerp.models.project_management import Initiative, Todo
from bloomerp.models.users.user import DetailSidebarViewPreference
from bloomerp.models.users.user_object_layout_preference import UserObjectLayoutPreference
from bloomerp.tests import base as test_base
from bloomerp.views.generic.detail.overview import BloomerpDetailOverviewView
from config.urls import urlpatterns as project_urlpatterns


urlpatterns = list(project_urlpatterns)


@override_settings(ROOT_URLCONF=__name__)
class TestBloomerpDetailOverviewView(test_base.BloomerpDetailViewTestCase):
    """Readable behavior contract for the generated object overview."""

    view_name = "overview"
    model = None
    create_foreign_models = True
    auto_create_customers = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model = cls.CustomerModel
        for route_name, model in (
            ("test_customer_overview", cls.CustomerModel),
            ("test_todo_overview", Todo),
            ("test_initiative_overview", Initiative),
        ):
            urlpatterns.append(
                path(
                    f"test/{route_name}/<uuid:pk>/",
                    BloomerpDetailOverviewView.as_view(model=model),
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
        self.customer = self.create_customer("Allowed", "Person", 30)
        self.content_type = ContentType.objects.get_for_model(self.CustomerModel)
        self._ensure_permissions_for_model(self.CustomerModel)
        self.fields_by_name = {
            field.field: field
            for field in ApplicationField.get_for_model(self.CustomerModel)
        }

    def create_test_object(self):
        return self.customer

    def get_test_scenarios(self) -> list[test_base.ModelRequestScenario]:
        customer_kwargs = {"pk": self.customer.pk}
        return [
            test_base.ModelRequestScenario(
                name="Object overview requires global view permission",
                description="UC: A row policy matches but global view access is absent.\nExpected Result: The detail page returns 403.",
                model=self.CustomerModel,
                user=self.normal_user,
                view_kwargs=customer_kwargs,
                prepare=self.grant_without_global_view,
                expected=test_base.ExpectedResult(status_code=403),
            ),
            test_base.ModelRequestScenario(
                name="Object overview renders only viewable fields",
                description="UC: A user can view first and last name only.\nExpected Result: Those fields render and age does not.",
                model=self.CustomerModel,
                user=self.normal_user,
                view_kwargs=customer_kwargs,
                prepare=self.grant_names_only,
                expected=test_base.ExpectedResult(response_validators=self.only_name_fields_render),
            ),
            test_base.ModelRequestScenario(
                name="View-only fields are disabled",
                description="UC: A user may view age but not change it.\nExpected Result: The age input renders disabled.",
                model=self.CustomerModel,
                user=self.normal_user,
                view_kwargs=customer_kwargs,
                prepare=self.grant_first_name_change,
                expected=test_base.ExpectedResult(response_validators=self.age_is_disabled),
            ),
            test_base.ModelRequestScenario(
                name="Generated layouts omit system fields but keep files editable",
                description="UC: An administrator opens an object using the generated default layout.\nExpected Result: Internal system fields are omitted while files stay visible and enabled.",
                model=self.CustomerModel,
                user=self.admin_user,
                view_kwargs=customer_kwargs,
                expected=test_base.ExpectedResult(response_validators=self.system_fields_have_correct_state),
            ),
            test_base.ModelRequestScenario(
                name="Regular object detail offers create-todo action",
                description="UC: An administrator opens a regular object.\nExpected Result: The create-todo side action is present.",
                model=self.CustomerModel,
                user=self.admin_user,
                view_kwargs=customer_kwargs,
                expected=test_base.ExpectedResult(response_validators=self.contains_text("/components/todo/create-todo-for-object/")),
            ),
            test_base.ModelRequestScenario(
                name="Persisted comments sidebar is loaded first",
                description="UC: A user selected Comments for detail sidebars.\nExpected Result: The initial sidebar request targets Comments.",
                model=self.CustomerModel,
                user=self.admin_user,
                view_kwargs=customer_kwargs,
                prepare=self.select_comments_sidebar,
                expected=test_base.ExpectedResult(response_validators=self.comments_sidebar_is_selected),
            ),
            test_base.ModelRequestScenario(
                name="Activity sidebar is the default",
                description="UC: A user has no detail-sidebar preference.\nExpected Result: The initial sidebar request targets Activity.",
                model=self.CustomerModel,
                user=self.admin_user,
                view_kwargs=customer_kwargs,
                prepare=self.reset_sidebar_preference,
                expected=test_base.ExpectedResult(response_validators=self.activity_sidebar_is_selected),
            ),
            test_base.ModelRequestScenario(
                name="Todo detail hides recursive create-todo action",
                description="UC: A user opens a Todo.\nExpected Result: The create-todo action is hidden.",
                model=Todo,
                user=self.admin_user,
                prepare=self.target_todo,
                expected=test_base.ExpectedResult(response_validators=self.does_not_contain_text("/components/todo/create-todo-for-object/")),
            ),
            test_base.ModelRequestScenario(
                name="Initiative detail hides recursive create-todo action",
                description="UC: A user opens an Initiative.\nExpected Result: The create-todo action is hidden.",
                model=Initiative,
                user=self.admin_user,
                prepare=self.target_initiative,
                expected=test_base.ExpectedResult(response_validators=self.does_not_contain_text("/components/todo/create-todo-for-object/")),
            ),
            test_base.ModelRequestScenario(
                name="Injected non-changeable field is rejected",
                description="UC: A user posts an age they may view but not change.\nExpected Result: A field-permission error renders and age is unchanged.",
                model=self.CustomerModel,
                method="POST",
                user=self.normal_user,
                view_kwargs=customer_kwargs,
                data={"first_name": "Allowed", "age": 31},
                prepare=self.grant_first_name_change_with_stable_row,
                expected=test_base.ExpectedResult(response_validators=[self.contains_text("Permission denied for fields: age"), self.age_is_unchanged]),
            ),
            test_base.ModelRequestScenario(
                name="Field validation errors render in their layout item",
                description="UC: A user submits invalid data for a changeable field.\nExpected Result: The field layout shows its validation state and the object is unchanged.",
                model=self.CustomerModel,
                method="POST",
                user=self.normal_user,
                view_kwargs=customer_kwargs,
                data={"age": "not-a-number"},
                prepare=self.grant_age_change,
                expected=test_base.ExpectedResult(response_validators=[self.age_error_is_visible, self.age_is_unchanged]),
            ),
            test_base.ModelRequestScenario(
                name="Permitted detail edit updates the object",
                description="UC: A user changes a field allowed by field and row policies.\nExpected Result: The request redirects and persists the new value.",
                model=self.CustomerModel,
                method="POST",
                user=self.normal_user,
                view_kwargs=customer_kwargs,
                data={"first_name": "Allowed Updated"},
                prepare=self.grant_first_name_change,
                expected=test_base.ExpectedResult(status_code=302, response_validators=self.first_name_was_updated),
            ),
            test_base.ModelRequestScenario(
                name="Detail available-items endpoint returns layout items",
                description="UC: A layout editor requests detail fields.\nExpected Result: Available layout items are returned.",
                model=self.CustomerModel,
                user=self.admin_user,
                view_name="detail_layout_available_fields",
                query_params={"content_type_id": self.content_type.pk},
                expected=test_base.ExpectedResult(response_validators=self.contains_text("data-layout-item-id")),
            ),
            test_base.ModelRequestScenario(
                name="Successful detail edit records activity provenance",
                description="UC: An administrator edits a Todo from its detail page.\nExpected Result: A CHANGE activity from DETAIL is recorded with updater attribution.",
                model=Todo,
                method="POST",
                user=self.admin_user,
                data={"title": "AFTER"},
                prepare=self.target_activity_todo,
                expected=test_base.ExpectedResult(status_code=302, response_validators=self.todo_activity_was_recorded),
            ),
        ]

    def get_endpoint(self, view_name, kwargs, setup=None):
        if view_name == "detail_layout_available_fields":
            preference_type = ContentType.objects.get_for_model(UserObjectLayoutPreference)
            return reverse(
                "components_available_layout_items",
                kwargs={"content_type_id": preference_type.pk},
            )
        route_name = {
            self.CustomerModel: "test_customer_overview",
            Todo: "test_todo_overview",
            Initiative: "test_initiative_overview",
        }[setup.model]
        return reverse(route_name, kwargs=kwargs)

    def _ensure_permissions_for_model(self, model):
        content_type = ContentType.objects.get_for_model(model)
        for action in model._meta.default_permissions:
            Permission.objects.get_or_create(codename=f"{action}_{model._meta.model_name}", content_type=content_type, defaults={"name": f"Can {action} {model._meta.verbose_name}"})

    @staticmethod
    def _group(rule):
        return rule if "conditions" in rule else {"connector": "OR", "conditions": [rule]}

    def grant_policy(self, *, view_fields, change_fields=(), global_view=True, global_change=True, condition_field="first_name", condition_value="Allowed"):
        view_code = f"view_{self.CustomerModel._meta.model_name}"
        change_code = f"change_{self.CustomerModel._meta.model_name}"
        rules = {str(self.fields_by_name[name].pk): [view_code] for name in view_fields}
        for name in change_fields:
            rules.setdefault(str(self.fields_by_name[name].pk), []).append(change_code)
        field_policy = FieldPolicy.objects.create(content_type=self.content_type, name="Overview field policy", rule=rules)
        row_policy = RowPolicy.objects.create(content_type=self.content_type, name="Overview row policy")
        condition = {"application_field_id": str(self.fields_by_name[condition_field].pk), "operator": lookups.EQUALS.id, "value": condition_value}
        for code in (view_code, change_code):
            row_rule = RowPolicyRule.objects.create(row_policy=row_policy, rule=self._group(condition))
            row_rule.add_permission(code)
        policy = Policy.objects.create(name="Overview policy", row_policy=row_policy, field_policy=field_policy)
        policy.assign_user(self.normal_user)
        for enabled, code in ((global_view, view_code), (global_change, change_code)):
            if enabled:
                permission = Permission.objects.get(content_type=self.content_type, codename=code)
                self.normal_user.user_permissions.add(permission)
                policy.global_permissions.add(permission)

    def grant_without_global_view(self, _scenario):
        self.grant_policy(view_fields=["first_name", "last_name", "age"], global_view=False, global_change=False)

    def grant_names_only(self, _scenario):
        self.grant_policy(view_fields=["first_name", "last_name"], global_change=False)

    def grant_first_name_change(self, _scenario):
        self.grant_policy(
            view_fields=["first_name", "last_name", "age"],
            change_fields=["first_name"],
            condition_field="age",
            condition_value=30,
        )

    def grant_age_change(self, _scenario):
        self.grant_policy(view_fields=["first_name", "last_name", "age"], change_fields=["age"])

    def grant_first_name_change_with_stable_row(self, _scenario):
        self.grant_policy(
            view_fields=["first_name", "age"],
            change_fields=["first_name"],
            condition_field="age",
            condition_value=30,
        )

    def only_name_fields_render(self, response):
        items = {str(item.id): item for row in response.context["layout"].rows for item in row.items}
        return (
            all(items[str(self.fields_by_name[name].pk)].is_visible for name in ("first_name", "last_name"))
            and not items[str(self.fields_by_name["age"].pk)].is_visible
        )

    def age_is_disabled(self, response):
        soup = BeautifulSoup(response.content, "html.parser")
        field = soup.find(attrs={"name": "age"})
        return field is not None and field.has_attr("disabled")

    def system_fields_have_correct_state(self, response):
        items = {str(item.id): item for row in response.context["layout"].rows for item in row.items}
        system_names = {"id", "pk", "datetime_created", "datetime_updated", "created_by", "updated_by", "comments"}
        return (
            all(str(self.fields_by_name[name].pk) not in items for name in system_names)
            and items[str(self.fields_by_name["files"].pk)].is_visible
            and "disabled" not in items[str(self.fields_by_name["files"].pk)].content
        )

    def select_comments_sidebar(self, _scenario):
        self.admin_user.detail_sidebar_view_preference = DetailSidebarViewPreference.COMMENTS
        self.admin_user.save(update_fields=["detail_sidebar_view_preference"])

    def reset_sidebar_preference(self, _scenario):
        self.admin_user.refresh_from_db()
        self.admin_user.detail_sidebar_view_preference = DetailSidebarViewPreference.ACTIVITY
        self.admin_user.save(update_fields=["detail_sidebar_view_preference"])

    def sidebar_url(self, response):
        node = BeautifulSoup(response.content, "html.parser").select_one("[data-detail-sidebar-loader]")
        return node.get("hx-get") if node else None

    def comments_sidebar_is_selected(self, response):
        return self.sidebar_url(response) == reverse("components_comments", kwargs={"content_type_id": self.content_type.pk, "object_id": self.customer.pk})

    def activity_sidebar_is_selected(self, response):
        expected = f'{reverse("components_activity_log")}?content_type_id={self.content_type.pk}&object_id={self.customer.pk}'
        return self.sidebar_url(response) == expected

    def target_todo(self, scenario):
        scenario.view_kwargs = {"pk": Todo.objects.create(title="No recursive action").pk}

    def target_initiative(self, scenario):
        scenario.view_kwargs = {"pk": Initiative.objects.create(name="Launch planning").pk}

    def age_is_unchanged(self, _response):
        self.customer.refresh_from_db()
        return self.customer.age == 30

    def age_error_is_visible(self, response):
        html = response.content.decode()
        return f'data-layout-item-id="{self.fields_by_name["age"].pk}"' in html and "border-red-500" in html

    def first_name_was_updated(self, _response):
        self.customer.refresh_from_db()
        return self.customer.first_name == "Allowed Updated"

    def target_activity_todo(self, scenario):
        self.activity_todo = Todo.objects.create(title="START")
        scenario.view_kwargs = {"pk": self.activity_todo.pk}

    def todo_activity_was_recorded(self, _response):
        activity = ActivityLog.objects.filter(object_id=self.activity_todo.pk, content_type=ContentType.objects.get_for_model(Todo)).first()
        self.activity_todo.refresh_from_db()
        return activity is not None and activity.action == ActivityLogAction.CHANGE and activity.source == ActivityLogSource.DETAIL and self.activity_todo.title == "AFTER" and self.activity_todo.updated_by == self.admin_user
