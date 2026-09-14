from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from bloomerp.models.project_management.todo import Todo
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.tests.base import BloomerpModelTestCase, ModelScenario
from bloomerp.tests.models.default_filters_scenarios import default_filter_scenarios


class TestUserListViewPreferenceModel(BloomerpModelTestCase):
    model = UserListViewPreference

    def setUp(self):
        self.owner = get_user_model().objects.create_user(username='owner')
        self.other_user = get_user_model().objects.create_user(username='recipient')
        self.content_type = ContentType.objects.get_for_model(Todo)

    def get_test_scenarios(self) -> list[ModelScenario[UserListViewPreference]]:
        return default_filter_scenarios(self, lambda: {
            'user': self.owner, 'content_type': self.content_type, 'name': 'List',
        })
