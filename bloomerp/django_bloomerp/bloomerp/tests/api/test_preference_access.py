"""Exercise owner name access through the generated preference APIs."""

from collections.abc import Callable

from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.users.base_preference import BasePreference
from bloomerp.models.users.user_detail_view_tabs_preference import (
    UserDetailViewTabsPreference,
)
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.models.users.user_object_layout_preference import (
    UserObjectLayoutPreference,
)
from bloomerp.models.workspaces.sidebar import Sidebar
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.tests.base import (
    BaseBloomerpTestCaseWithModels,
    ExpectedResult,
    RequestScenario,
    RequestTestCaseMixin,
)
from bloomerp.utils.models import model_name_plural_underline
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse


class TestPreferenceApiAccess(RequestTestCaseMixin, BaseBloomerpTestCaseWithModels):
    """Verify generated DRF routes with the shared request scenario framework."""

    # Generated DRF routes are outside Bloomerp's view route registry.
    view_name = "user_list_view_preferences-detail"
    auto_create_customers = False
    preference_models = (
        UserListViewPreference,
        UserObjectLayoutPreference,
        UserDetailViewTabsPreference,
        Sidebar,
        Workspace,
        Inbox,
    )

    def setUp(self) -> None:
        """Create owned and shared preferences without granting model permissions."""
        super().setUp()
        self.preferences: list[tuple[BasePreference, BasePreference]] = []
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        for model in self.preference_models:
            scope = (
                {"content_type": content_type}
                if "content_type" in model.preference_scope_fields
                else {}
            )
            owned = model.objects.create(user=self.normal_user, name="Owned", **scope)
            shared = model.objects.create(user=self.admin_user, name="Shared", **scope)
            shared.shared_with_users.add(self.normal_user)
            self.preferences.append((owned, shared))
            self.assertFalse(
                self.normal_user.has_perm(f"bloomerp.change_{model._meta.model_name}")
            )

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover name edits, field restrictions, ownership and authentication."""
        scenarios: list[RequestScenario] = []
        for owned, shared in self.preferences:
            model = type(owned)
            route = f"{model_name_plural_underline(model)}-detail"
            for label, user, preference in (
                ("owner without model permissions", self.normal_user, owned),
                ("superuser", self.admin_user, shared),
            ):
                scenarios.append(
                    RequestScenario(
                        name=f"{model.__name__}: {label} renames their preference",
                        view_name=route,
                        method="PATCH",
                        user=user,
                        view_kwargs={"pk": preference.pk},
                        content_type="application/json",
                        data={"name": "Renamed"},
                        expected=ExpectedResult(
                            response_validators=self.name_is(preference, "Renamed")
                        ),
                    )
                )
            scenarios.append(
                RequestScenario(
                    name=f"{model.__name__}: owner reads only identity and name",
                    view_name=route,
                    user=self.normal_user,
                    view_kwargs={"pk": owned.pk},
                    expected=ExpectedResult(
                        response_validators=self.json_exact(
                            {"id": owned.pk, "name": "Owned"}
                        )
                    ),
                )
            )
            for label, user, preference, data, status in (
                (
                    "sharing does not grant rename access",
                    self.normal_user,
                    shared,
                    {"name": "Stolen"},
                    404,
                ),
                (
                    "owner cannot change ownership",
                    self.normal_user,
                    owned,
                    {"user": self.admin_user.pk, "name": "Stolen"},
                    403,
                ),
                ("anonymous rename is denied", None, owned, {"name": "Stolen"}, 401),
            ):
                scenarios.append(
                    RequestScenario(
                        name=f"{model.__name__}: {label}",
                        view_name=route,
                        method="PATCH",
                        user=user,
                        view_kwargs={"pk": preference.pk},
                        content_type="application/json",
                        data=data,
                        expected=ExpectedResult(
                            status_code=status,
                            response_validators=self.name_is(
                                preference, preference.name
                            ),
                        ),
                    )
                )
        return scenarios

    def name_is(
        self, preference: BasePreference, name: str
    ) -> Callable[[HttpResponse], bool]:
        """Validate the persisted name after a successful or denied request."""

        def validate_name(response: HttpResponse) -> bool:
            """Refresh the preference to check whether the request changed its name."""
            preference.refresh_from_db()
            return preference.name == name

        return validate_name
