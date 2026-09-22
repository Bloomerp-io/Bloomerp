from bs4 import BeautifulSoup
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.urls import reverse

from bloomerp.lookups import builtins as lookups
from bloomerp.models import (
    ApplicationField,
    FieldLayout,
    FieldPolicy,
    LayoutItem,
    LayoutRow,
    Policy,
    RowPolicy,
    RowPolicyRule,
)
from bloomerp.models.audit.activity_log import (
    ActivityLog,
    ActivityLogAction,
    ActivityLogSource,
)
from bloomerp.models.project_management import Initiative, Todo
from bloomerp.models.users.user import DetailSidebarViewPreference
from bloomerp.models.users.user_object_layout_preference import (
    UserObjectLayoutPreference,
)
from bloomerp.tests.base.request_test_case_mixin import (
    ExpectedResult,
    ModelRequestScenario,
)
from bloomerp.tests.base.view_test_case import BloomerpDetailViewTestCase


class TestBloomerpDetailOverviewView(BloomerpDetailViewTestCase):
    """Readable behavior contract for the generated object overview."""

    view_name = "overview"
    create_foreign_models = True
    auto_create_customers = False

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

    def get_test_scenarios(self) -> list[ModelRequestScenario]:
        """Return the permission, layout, persistence, and activity scenarios."""
        customer_kwargs = {"pk": self.customer.pk}
        return [
            ModelRequestScenario(
                name="Object overview requires global view permission",
                description="UC: A row policy matches but global view access is absent.\nExpected Result: The detail page returns 403.",
                model=self.CustomerModel,
                user=self.normal_user,
                view_kwargs=customer_kwargs,
                prepare=self.grant_without_global_view,
                expected=ExpectedResult(status_code=403),
            ),
            ModelRequestScenario(
                name="Object overview renders only viewable fields",
                description="UC: A user can view first and last name only.\nExpected Result: Those fields render and age does not.",
                model=self.CustomerModel,
                user=self.normal_user,
                view_kwargs=customer_kwargs,
                prepare=self.grant_names_only,
                expected=ExpectedResult(response_validators=self.only_name_fields_render),
            ),
            ModelRequestScenario(
                name="View-only fields are disabled",
                description="UC: A user may view age but not change it.\nExpected Result: The age input renders disabled.",
                model=self.CustomerModel,
                user=self.normal_user,
                view_kwargs=customer_kwargs,
                prepare=self.grant_first_name_change,
                expected=ExpectedResult(response_validators=self.age_is_disabled),
            ),
            ModelRequestScenario(
                name="Generated layouts omit system fields but keep files editable",
                description="UC: An administrator opens an object using the generated default layout.\nExpected Result: Internal system fields are omitted while files stay visible and enabled.",
                model=self.CustomerModel,
                user=self.admin_user,
                view_kwargs=customer_kwargs,
                expected=ExpectedResult(response_validators=self.system_fields_have_correct_state),
            ),
            ModelRequestScenario(
                name="Deleted application field is skipped in saved detail layout",
                description="UC: A saved layout references a deleted field.\nExpected Result: The overview renders its remaining field without an error.",
                model=self.CustomerModel,
                user=self.admin_user,
                view_kwargs=customer_kwargs,
                prepare=self.configure_layout_with_deleted_field,
                expected=ExpectedResult(
                    status_code=200,
                    response_validators=self.deleted_field_is_skipped,
                ),
            ),
            ModelRequestScenario(
                name="Regular object detail offers create-todo action",
                description="UC: An administrator opens a regular object.\nExpected Result: The create-todo side action is present.",
                model=self.CustomerModel,
                user=self.admin_user,
                view_kwargs=customer_kwargs,
                expected=ExpectedResult(response_validators=self.contains_text("/components/todo/create-todo-for-object/")),
            ),
            ModelRequestScenario(
                name="Persisted comments sidebar is loaded first",
                description="UC: A user selected Comments for detail sidebars.\nExpected Result: The initial sidebar request targets Comments.",
                model=self.CustomerModel,
                user=self.admin_user,
                view_kwargs=customer_kwargs,
                prepare=self.select_comments_sidebar,
                expected=ExpectedResult(response_validators=self.comments_sidebar_is_selected),
            ),
            ModelRequestScenario(
                name="Activity sidebar is the default",
                description="UC: A user has no detail-sidebar preference.\nExpected Result: The initial sidebar request targets Activity.",
                model=self.CustomerModel,
                user=self.admin_user,
                view_kwargs=customer_kwargs,
                prepare=self.reset_sidebar_preference,
                expected=ExpectedResult(response_validators=self.activity_sidebar_is_selected),
            ),
            ModelRequestScenario(
                name="Todo detail hides recursive create-todo action",
                description="UC: A user opens a Todo.\nExpected Result: The create-todo action is hidden.",
                model=Todo,
                user=self.admin_user,
                prepare=self.target_todo,
                expected=ExpectedResult(response_validators=self.does_not_contain_text("/components/todo/create-todo-for-object/")),
            ),
            ModelRequestScenario(
                name="Initiative detail hides recursive create-todo action",
                description="UC: A user opens an Initiative.\nExpected Result: The create-todo action is hidden.",
                model=Initiative,
                user=self.admin_user,
                prepare=self.target_initiative,
                expected=ExpectedResult(response_validators=self.does_not_contain_text("/components/todo/create-todo-for-object/")),
            ),
            ModelRequestScenario(
                name="Injected non-changeable field is rejected",
                description="UC: A user posts an age they may view but not change.\nExpected Result: A field-permission error renders and age is unchanged.",
                model=self.CustomerModel,
                method="POST",
                user=self.normal_user,
                view_kwargs=customer_kwargs,
                data={"first_name": "Allowed", "age": 31},
                prepare=self.grant_first_name_change_with_stable_row,
                expected=ExpectedResult(response_validators=[self.contains_text("Permission denied for fields: age"), self.age_is_unchanged]),
            ),
            ModelRequestScenario(
                name="Field validation errors render in their layout item",
                description="UC: A user submits invalid data for a changeable field.\nExpected Result: The field layout shows its validation state and the object is unchanged.",
                model=self.CustomerModel,
                method="POST",
                user=self.normal_user,
                view_kwargs=customer_kwargs,
                data={"age": "not-a-number"},
                prepare=self.grant_age_change,
                expected=ExpectedResult(response_validators=[self.age_error_is_visible, self.age_is_unchanged]),
            ),
            ModelRequestScenario(
                name="Permitted detail edit updates the object",
                description="UC: A user changes a field allowed by field and row policies.\nExpected Result: The request redirects and persists the new value.",
                model=self.CustomerModel,
                method="POST",
                user=self.normal_user,
                view_kwargs=customer_kwargs,
                data={"first_name": "Allowed Updated"},
                prepare=self.grant_first_name_change,
                expected=ExpectedResult(status_code=302, response_validators=self.first_name_was_updated),
            ),
            ModelRequestScenario(
                name="One-to-many avatar upload persists",
                description="UC: An administrator adds a related object with an avatar through an explicit inline layout.\nExpected Result: The related object and its avatar are persisted.",
                model=self.CountryModel,
                method="POST",
                user=self.admin_user,
                view_kwargs={"pk": self.CountryModel.objects.get(name="Belgium").pk},
                data={
                    "customers__0__first_name": "Avatar",
                    "customers__0__last_name": "Customer",
                    "customers__0__age": 31,
                    "customers__0__avatar": SimpleUploadedFile(
                        "inline-avatar.gif",
                        b"GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00ccc,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
                        content_type="image/gif",
                    ),
                },
                prepare=self.configure_one_to_many_avatar_layout,
                expected=ExpectedResult(
                    status_code=302,
                    response_validators=self.one_to_many_avatar_was_saved,
                ),
            ),
            ModelRequestScenario(
                name="Detail available-items endpoint returns layout items",
                description="UC: A layout editor requests detail fields.\nExpected Result: Available layout items are returned.",
                model=self.CustomerModel,
                user=self.admin_user,
                view_name="detail_layout_available_fields",
                query_params={"content_type_id": self.content_type.pk},
                expected=ExpectedResult(response_validators=self.contains_text("data-layout-item-id")),
            ),
            ModelRequestScenario(
                name="Successful detail edit records activity provenance",
                description="UC: An administrator edits a Todo from its detail page.\nExpected Result: A CHANGE activity from DETAIL is recorded with updater attribution.",
                model=Todo,
                method="POST",
                user=self.admin_user,
                data={"title": "AFTER"},
                prepare=self.target_activity_todo,
                expected=ExpectedResult(status_code=302, response_validators=self.todo_activity_was_recorded),
            ),
        ]

    def get_endpoint(self, view_name, kwargs, setup=None):
        if view_name == "detail_layout_available_fields":
            preference_type = ContentType.objects.get_for_model(UserObjectLayoutPreference)
            return reverse(
                "components_available_layout_items",
                kwargs={"content_type_id": preference_type.pk},
            )
        return super().get_endpoint(view_name, kwargs, setup)


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

    def configure_layout_with_deleted_field(
        self, _scenario: ModelRequestScenario
    ) -> None:
        """Save a detail layout with one valid field and one deleted field ID."""
        missing_id = ApplicationField.objects.order_by("-pk").values_list("pk", flat=True).first()
        self.deleted_field_id = (missing_id or 0) + 1
        UserObjectLayoutPreference.objects.filter(
            user=self.admin_user,
            content_type=self.content_type,
        ).delete()
        UserObjectLayoutPreference.objects.create(
            user=self.admin_user,
            content_type=self.content_type,
            selected=True,
            layout=FieldLayout(
                rows=[LayoutRow(columns=2, items=[
                    LayoutItem(id=self.fields_by_name["first_name"].pk),
                    LayoutItem(id=self.deleted_field_id),
                ])]
            ).model_dump(mode="json"),
        )

    def deleted_field_is_skipped(self, response: HttpResponse) -> bool:
        """Check that the valid field remains and the stale item is absent."""
        item_ids = {
            str(item.id)
            for row in response.context["layout"].rows
            for item in row.items
        }
        return (
            str(self.fields_by_name["first_name"].pk) in item_ids
            and str(self.deleted_field_id) not in item_ids
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

    def configure_one_to_many_avatar_layout(
        self,
        _scenario: ModelRequestScenario,
    ) -> None:
        """Select a country detail layout that exposes the customer avatar column."""
        content_type = ContentType.objects.get_for_model(self.CountryModel)
        customers_field = ApplicationField.get_by_field(
            self.CountryModel,
            "customers",
        )
        UserObjectLayoutPreference.objects.filter(
            user=self.admin_user,
            content_type=content_type,
        ).delete()
        UserObjectLayoutPreference.objects.create(
            user=self.admin_user,
            content_type=content_type,
            selected=True,
            layout=FieldLayout(
                rows=[
                    LayoutRow(
                        columns=1,
                        items=[
                            LayoutItem(
                                id=customers_field.pk,
                                config={
                                    "inline_fields": [
                                        "first_name",
                                        "last_name",
                                        "age",
                                        "avatar",
                                    ]
                                },
                            )
                        ],
                    )
                ]
            ).model_dump(mode="json"),
        )

    def one_to_many_avatar_was_saved(self, _response: HttpResponse) -> bool:
        """Return whether the inline customer retained its uploaded avatar."""
        customer = self.CustomerModel.objects.filter(
            first_name="Avatar",
            last_name="Customer",
        ).first()
        return customer is not None and bool(customer.avatar)

    def target_activity_todo(self, scenario):
        self.activity_todo = Todo.objects.create(title="START")
        scenario.view_kwargs = {"pk": self.activity_todo.pk}

    def todo_activity_was_recorded(self, _response):
        activity = ActivityLog.objects.filter(object_id=self.activity_todo.pk, content_type=ContentType.objects.get_for_model(Todo)).first()
        self.activity_todo.refresh_from_db()
        return activity is not None and activity.action == ActivityLogAction.CHANGE and activity.source == ActivityLogSource.DETAIL and self.activity_todo.title == "AFTER" and self.activity_todo.updated_by == self.admin_user
