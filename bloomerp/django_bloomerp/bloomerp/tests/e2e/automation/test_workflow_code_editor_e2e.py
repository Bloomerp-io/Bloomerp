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

        for index, query in enumerate(("SELECT 2", "SELECT 3")):
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
            if index:
                self.assertTrue(self.page.evaluate("window.__previousWorkflowWidget.destroyed"))
            else:
                editor.evaluate(
                    "element => { window.__previousWorkflowWidget = "
                    "element.closest('[bloomerp-component]').__bloomerp_component; }"
                )

            editor.click()
            editor.evaluate("element => element.env.editor.selectAll()")
            self.page.keyboard.type(query)
            expect(self.page.locator("[data-code-editor-input]")).to_have_value(query)

            modal = self.page.locator("#bloomerp-general-use-modal")
            modal.locator('[bloomerp-close-modal="bloomerp-general-use-modal"]').click()
            expect(modal).to_be_hidden()
