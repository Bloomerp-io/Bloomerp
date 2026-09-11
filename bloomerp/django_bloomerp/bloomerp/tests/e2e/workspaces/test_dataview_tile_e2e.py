


from bloomerp.models.project_management.todo import Todo
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.tests.base.e2e_test_case import BloomerpE2ETestCase, E2ERequestScenario


class TestDataviewTileE2E(BloomerpE2ETestCase):
    
    
    
    def get_test_scenarios(self):
        workspace = Workspace.objects.create(
            name="Test workspace",
            created_by=self.admin_user,
        )
        
        todo_ct = self.get_content_type_for_model(Todo)
        
        
        return [
            E2ERequestScenario(
                name="Multiple dataview tiles work",
                user=self.admin_user,
                url=workspace.get_absolute_url(),
                actions=[
                    self.input_field(f"data-view-search-input-{todo_ct.id}"),
                    self.click(f"[id^='data-view-search-input-{todo_ct.id}']")
                ]
            )
        ]