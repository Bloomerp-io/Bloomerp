from unittest.mock import patch

from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.models.project_management.todo import Todo
from bloomerp.permissions.definition import AccessRule, BloomerpPermission, RowPolicyRuleCondition, RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.tests.base import (
    BloomerpDetailViewTestCase,
    ExpectedResult,
    RequestScenario,
    ModelRequestScenario,
)


class TestBloomerpDeleteView(BloomerpDetailViewTestCase):
    view_name = 'delete'
    model = Todo
    
    def _give_access_to_normal_user(self, setup:RequestScenario):
        policy = PolicyManager.create_policy(
            model_or_content_type=Todo,
            access_rule=AccessRule(
                row_permissions=[
                    RowPolicyRuleContent(
                        permissions=[BloomerpPermission.DELETE],
                        conditions=[
                            RowPolicyRuleCondition(
                                field='__all__'
                            )
                        ]
                    )
                ],
                field_permissions={}
            ),
            global_permissions=BloomerpPermission.DELETE
        )
        PolicyManager.assign(policy, self.normal_user)
        
    
    def create_test_object(self):
        return Todo.objects.create(
            title="Hello"
        )
    
    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover deletion permissions and model-wide exclusions on detail lookups."""
        self.get_test_object()
        self.normal_user.is_staff = True
        self.normal_user.save()
        
        return [
            RequestScenario(
                name="Accessible by admin user",
                method="GET",
                user=self.admin_user,
                expected=ExpectedResult(200)
            ),
            RequestScenario(
                name="Not accessible by regular user",
                method="GET",
                user=self.normal_user,
                expected=ExpectedResult(403)
            ),
            RequestScenario(
                name="Accessible by regular user with the right perm",
                method="GET",
                user=self.normal_user,
                expected=ExpectedResult(200),
                prepare=self._give_access_to_normal_user
            ),
            RequestScenario(
                name="Base-filtered record is unavailable to an administrator",
                user=self.admin_user,
                prepare=self._exclude_test_object,
                cleanup=self._restore_model_config,
                expected=ExpectedResult(status_code=404),
            ),
            RequestScenario(
                name="Base-filtered record is unavailable despite delete permission",
                user=self.normal_user,
                prepare=self._exclude_test_object,
                cleanup=self._restore_model_config,
                expected=ExpectedResult(status_code=404),
            ),
            RequestScenario(
                name="Object get's deleted",
                method="POST",
                user=self.admin_user,
                expected=ExpectedResult(
                    status_code=302,
                    response_validators=[
                        lambda _: Todo.objects.count() == 0 
                    ]
                )
            ),
            RequestScenario(
                name="Normal user can't delete",
                method="POST",
                user=self.normal_user,
                expected=ExpectedResult(
                    status_code=403,
                    response_validators=[
                        lambda _: Todo.objects.count() == 1 
                    ]
                )
            ),
            
        ]

    def _exclude_test_object(self, scenario: RequestScenario) -> None:
        """Grant delete access while excluding the fixture from application reads."""
        self._give_access_to_normal_user(scenario)
        config = Todo.bloomerp_config.model_copy(
            update={
                "base_filter": Filter(
                    connector="AND",
                    conditions=[
                        FilterCondition(
                            field_path="title",
                            lookup_id="equals",
                            value="Visible record",
                        )
                    ],
                )
            }
        )
        self.base_filter_patch = patch.object(Todo, "bloomerp_config", config)
        self.base_filter_patch.start()

    def _restore_model_config(self, _scenario: RequestScenario) -> None:
        """Restore the model configuration before the next request scenario."""
        self.base_filter_patch.stop()
