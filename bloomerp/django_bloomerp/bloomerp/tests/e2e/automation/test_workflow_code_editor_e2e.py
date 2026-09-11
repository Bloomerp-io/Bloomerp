from playwright.sync_api import expect

from bloomerp.models.automation.workflow import Workflow
from bloomerp.models.automation.workflow_node import WorkflowNode
from bloomerp.tests.base import e2e_test_case as e2e


class TestWorkflowCodeEditorE2E(e2e.BloomerpE2ETestCase):
    def prepare_workflow(self):
        self.workflow = Workflow.objects.create(name="Code editor lifecycle")
        self.first = WorkflowNode.objects.create(
            workflow=self.workflow,
            type="ACTION",
            sub_type="SQL_QUERY",
            name="First query",
            parameters={"query": "SELECT 1", "page_size": 100},
            pos_x=0,
            pos_y=0,
        )
        self.second = WorkflowNode.objects.create(
            workflow=self.workflow,
            type="ACTION",
            sub_type="SQL_QUERY",
            name="Second query",
            parameters={"query": "SELECT 20", "page_size": 100},
            pos_x=360,
            pos_y=0,
        )

    def get_test_scenarios(self):
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
        nodes = self.page.locator("#drawflow .drawflow-node")
        expect(nodes).to_have_count(2)
        first_node = nodes.filter(has_text="First query")
        second_node = nodes.filter(has_text="Second query")

        editor = self.open_editor(first_node)
        self.assert_editor_theme_initialized(editor)
        editor.evaluate(
            "element => { window.__previousWorkflowWidget = "
            "element.closest('[bloomerp-component]').__bloomerp_component; }"
        )
        self.close_editor()

        route_pattern = "**/components/automation/render_workflow_node/**"
        self.page.route(route_pattern, lambda route: route.abort(), times=1)
        with self.page.expect_event(
            "requestfailed",
            predicate=lambda request: "/components/automation/render_workflow_node/" in request.url,
        ):
            second_node.dblclick()

        editor = self.page.locator("[data-code-editor-container]")
        expect(editor).to_be_visible()
        self.assertFalse(self.page.evaluate("window.__previousWorkflowWidget.destroyed"))
        with self.page.expect_request(
            lambda request: "/components/automation/save_workflow/" in request.url
        ) as saved:
            self.replace_editor_value(editor, "SELECT 2 FROM failed_request")

        payload = saved.value.post_data_json
        first_payload = next(node for node in payload["nodes"] if node.get("id") == self.first.pk)
        second_payload = next(node for node in payload["nodes"] if node.get("id") == self.second.pk)
        self.assertEqual(first_payload["parameters"]["query"], "SELECT 2 FROM failed_request")
        self.assertEqual(second_payload["parameters"]["query"], "SELECT 20")
        self.close_editor()

        editor = self.open_editor(second_node)
        self.assertTrue(self.page.evaluate("window.__previousWorkflowWidget.destroyed"))
        self.assert_editor_theme_initialized(editor)
        expect(self.page.locator("[data-code-editor-input]")).to_have_value("SELECT 20")
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

    def assert_editor_theme_initialized(self, editor):
        self.assertTrue(
            editor.evaluate(
                "element => element.classList.contains('ace-chrome') || "
                "element.classList.contains('ace-tomorrow-night')"
            )
        )

    def close_editor(self):
        modal = self.page.locator("#bloomerp-general-use-modal")
        modal.locator('[bloomerp-close-modal="bloomerp-general-use-modal"]').click()
        expect(modal).to_be_hidden()
