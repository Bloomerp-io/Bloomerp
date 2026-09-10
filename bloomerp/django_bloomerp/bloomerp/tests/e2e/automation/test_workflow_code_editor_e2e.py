from playwright.sync_api import expect

from bloomerp.models.automation.workflow import Workflow
from bloomerp.models.automation.workflow_node import WorkflowNode
from bloomerp.tests.base import e2e_test_case as e2e


class TestWorkflowCodeEditorE2E(e2e.BloomerpE2ETestCase):
    def prepare_workflow(self):
        self.workflow = Workflow.objects.create(name="Code editor lifecycle")
        WorkflowNode.objects.create(
            workflow=self.workflow,
            type="ACTION",
            sub_type="SQL_QUERY",
            name="Query",
            parameters={"query": "SELECT 1", "page_size": 100},
            pos_x=0,
            pos_y=0,
        )

    def get_request_setups(self):
        return [
            e2e.E2ERequestSetup(
                name="Code editor survives reopening node configuration",
                user=self.admin_user,
                prepare=self.prepare_workflow,
                url=lambda: f"/automation/workflows/{self.workflow.pk}/builder/",
                actions=[e2e.E2EAction(execute=self.reopen_code_editor)],
            )
        ]

    def reopen_code_editor(self):
        node = self.page.locator("#drawflow .drawflow-node").first
        expect(node).to_be_visible()

        editor = self.open_editor(node)
        editor.evaluate(
            "element => { window.__previousWorkflowWidget = "
            "element.closest('[bloomerp-component]').__bloomerp_component; }"
        )
        self.replace_editor_value(editor, "SELECT 2")
        self.close_editor()

        route_pattern = "**/components/automation/render_workflow_node/**"
        self.page.route(route_pattern, lambda route: route.abort(), times=1)
        with self.page.expect_event(
            "requestfailed",
            predicate=lambda request: "/components/automation/render_workflow_node/" in request.url,
        ):
            node.dblclick()

        editor = self.page.locator("[data-code-editor-container]")
        expect(editor).to_be_visible()
        self.assertFalse(self.page.evaluate("window.__previousWorkflowWidget.destroyed"))
        self.replace_editor_value(editor, "SELECT 2 FROM failed_request")
        self.close_editor()

        editor = self.open_editor(node)
        self.assertTrue(self.page.evaluate("window.__previousWorkflowWidget.destroyed"))
        self.replace_editor_value(editor, "SELECT 3")
        self.close_editor()

    def open_editor(self, node):
        with self.page.expect_response(
            lambda response: "/components/automation/render_workflow_node/" in response.url
        ):
            node.dblclick()

        editor = self.page.locator("[data-code-editor-container]")
        expect(editor).to_be_visible()
        self.page.wait_for_function(
            "element => Boolean(element.env?.editor)",
            arg=editor.element_handle(),
        )
        return editor

    def replace_editor_value(self, editor, value):
        editor.click()
        editor.evaluate("element => element.env.editor.selectAll()")
        self.page.keyboard.type(value)
        expect(self.page.locator("[data-code-editor-input]")).to_have_value(value)

    def close_editor(self):
        modal = self.page.locator("#bloomerp-general-use-modal")
        modal.locator('[bloomerp-close-modal="bloomerp-general-use-modal"]').click()
        expect(modal).to_be_hidden()
