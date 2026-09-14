from django.contrib.auth import get_user_model

from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.tests.base import BloomerpModelTestCase, ModelScenario
from bloomerp.tests.models.default_filters_scenarios import default_filter_scenarios
from bloomerp.workspaces.utils import has_access_to_workspace


class TestWorkspaceModel(BloomerpModelTestCase):
    model = Workspace

    def setUp(self):
        self.owner = get_user_model().objects.create_user(username='owner')
        self.other_user = get_user_model().objects.create_user(username='recipient')

    def get_test_scenarios(self) -> list[ModelScenario[Workspace]]:
        return [
            *default_filter_scenarios(self, lambda: {'user': self.owner, 'name': 'Workspace'}),
            ModelScenario(
                name='Sharing grants access and revocation removes it',
                description='UC: Share and revoke a workspace.\nExpected Result: References do not retain revoked access.',
                create_args=lambda: {'user': self.owner, 'name': 'Shared workspace'},
                create_validators=self.check_shared_access,
            ),
        ]

    def check_shared_access(self, workspace):
        self.assertTrue(has_access_to_workspace(workspace, self.owner))
        self.assertFalse(has_access_to_workspace(workspace, self.other_user))
        workspace.shared_with_users.add(self.other_user)
        reference = Workspace.objects.create(user=self.other_user, source_object=workspace)
        self.assertTrue(has_access_to_workspace(workspace, self.other_user))
        self.assertTrue(has_access_to_workspace(reference, self.other_user))
        workspace.shared_with_users.clear()
        self.assertFalse(has_access_to_workspace(workspace, self.other_user))
        self.assertFalse(has_access_to_workspace(reference, self.other_user))
        return True
