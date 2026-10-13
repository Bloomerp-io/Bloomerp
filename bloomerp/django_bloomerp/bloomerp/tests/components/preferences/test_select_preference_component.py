from bs4 import BeautifulSoup
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse
from django.urls import reverse

from bloomerp.models import Sidebar
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestSelectPreferenceComponent(BloomerpComponentTestCase):
    """Tests the preference-selection component."""

    view_name = "components_select_preference"

    def setUp(self) -> None:
        super().setUp()
        Sidebar.objects.create(
            user=self.admin_user,
            name="Primary",
            selected=True,
        )
        self.deletable = Sidebar.objects.create(
            user=self.admin_user,
            name="Temporary",
            selected=False,
        )

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Verify owner controls and scoped visibility through direct and overlapping group shares."""
        delete_url_template = reverse(
            "components_delete_preference",
            kwargs={"model": "Sidebar", "preference_id": "REPLACE_WITH_ID"},
        )
        return [
            RequestScenario(
                name="render owner delete action",
                user=self.admin_user,
                view_kwargs={"model": "Sidebar"},
                headers={"HX-Request": "true"},
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text(
                            f'data-delete-preference="{self.deletable.pk}"'
                        ),
                        self.contains_text(delete_url_template),
                    ],
                ),
            ),
            RequestScenario(
                name="Overlapping shares render each available preference once",
                user=self.admin_user,
                view_kwargs={"model": "UserListViewPreference"},
                prepare=self.prepare_shared_preferences,
                expected=ExpectedResult(
                    response_validators=self.validate_shared_preferences
                ),
            ),
            RequestScenario(
                name="Revoked shares hide their sources and existing selected references",
                user=self.admin_user,
                view_kwargs={"model": "UserListViewPreference"},
                prepare=self.prepare_revoked_preferences,
                expected=ExpectedResult(
                    response_validators=self.validate_shared_preferences
                ),
            ),
        ]

    def prepare_shared_preferences(self, scenario: RequestScenario) -> None:
        """Create overlapping shares, a live reference, inaccessible entries and another scope."""
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        scenario.query_params = {"content_type_id": content_type.pk}
        self.sharing_groups = [
            Group.objects.create(name=f"Preference group {index}")
            for index in range(3)
        ]
        for group in self.sharing_groups:
            group.user_set.add(self.admin_user, self.normal_user)
        self.owned = UserListViewPreference.objects.create(
            user=self.admin_user, content_type=content_type, name="Owned"
        )
        self.shared_sources = [
            UserListViewPreference.objects.create(
                user=self.normal_user, content_type=content_type, name=name
            )
            for name in ["Live source", "Group source", "Overlapping source"]
        ]
        self.shared_sources[0].shared_with_users.add(self.admin_user)
        self.shared_sources[1].shared_with_groups.add(*self.sharing_groups)
        self.shared_sources[2].shared_with_users.add(self.admin_user, self.normal_user)
        self.shared_sources[2].shared_with_groups.add(*self.sharing_groups)
        reference = UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=content_type,
            source_object=self.shared_sources[0],
            name="Stale reference name",
            selected=True,
        )
        UserListViewPreference.objects.create(
            user=self.normal_user, content_type=content_type, name="Private"
        )
        other_scope = UserListViewPreference.objects.create(
            user=self.normal_user,
            content_type=ContentType.objects.get_for_model(Sidebar),
            name="Other scope",
        )
        other_scope.shared_with_users.add(self.admin_user)
        self.expected_preferences = {
            str(self.owned.pk): "Owned",
            str(reference.pk): "Live source",
            str(self.shared_sources[1].pk): "Group source",
            str(self.shared_sources[2].pk): "Overlapping source",
        }

    def prepare_revoked_preferences(self, scenario: RequestScenario) -> None:
        """Revoke direct shares and group membership while leaving the selected reference stored."""
        self.prepare_shared_preferences(scenario)
        for source in self.shared_sources:
            source.shared_with_users.clear()
        for group in self.sharing_groups:
            group.user_set.remove(self.admin_user)
        self.expected_preferences = {str(self.owned.pk): "Owned"}

    def validate_shared_preferences(self, response: HttpResponse) -> bool:
        """Verify visible IDs and live source names with no duplicate preference rows."""
        soup = BeautifulSoup(response.content, "html.parser")
        buttons = soup.select("[data-select-preference]")
        self.assertEqual(len(buttons), len(self.expected_preferences))
        actual = {
            button["data-select-preference"]: button.get_text(strip=True)
            for button in buttons
        }
        self.assertEqual(actual, self.expected_preferences)
        return True
