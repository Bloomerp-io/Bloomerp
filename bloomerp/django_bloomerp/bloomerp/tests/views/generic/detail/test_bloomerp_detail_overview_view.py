from bloomerp.models.audit.activity_log import ActivityLog, ActivityLogAction, ActivityLogSource
from bloomerp.models.project_management.todo import Todo
from bloomerp.tests.base import (
    BloomerpDetailViewTestCase,
    ExpectedResult,
    RequestScenario,
    ModelRequestScenario,
)



class TestBloomerpDetailOverviewView(BloomerpDetailViewTestCase):
    """Tests class `BloomerpDetailOverviewView` from `bloomerp/views/generic/detail/overview.py`."""

    view_name = 'overview'
    model = Todo

    START_TITLE = "START"
    AFTER_TITLE = "AFTER"
    
    def create_test_object(self):
        return Todo.objects.create(title=self.START_TITLE)
        
    
    def get_test_scenarios(self) -> list[RequestScenario]:
        # Add only the route scenarios this callable needs.
        return [
            RequestScenario(
                name="Activity log test case",
                method="POST",
                user=self.admin_user,
                data={
                    "title" : self.AFTER_TITLE
                },
                expected=ExpectedResult(
                    status_code=302,
                    response_validators=[
                        lambda _: (
                            ActivityLog.objects.filter(
                            object_id=self.get_test_object().pk,
                            content_type_id=self.get_content_type_for_model(self.model)
                        ).first().action == ActivityLogAction.CHANGE
                        and
                        ActivityLog.objects.filter(
                            object_id=self.get_test_object().pk,
                            content_type_id=self.get_content_type_for_model(self.model)
                        ).first().source == ActivityLogSource.DETAIL
                        and
                        Todo.objects.get(id=self.get_test_object().pk).title == self.AFTER_TITLE
                        and
                        Todo.objects.get(id=self.get_test_object().pk).updated_by == self.admin_user
                        )
                    ]
                )
            ),
        ]
