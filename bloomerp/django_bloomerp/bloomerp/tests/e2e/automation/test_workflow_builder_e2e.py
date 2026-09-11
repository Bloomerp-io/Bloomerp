import re

from playwright.sync_api import expect

from bloomerp.models.automation.workflow import Workflow
from bloomerp.models.automation.workflow_node import WorkflowNode
from bloomerp.models.automation.workflow_edge import WorkflowEdge
from bloomerp.tests.base import e2e_test_case as e2e


class TestWorkflowBuilderE2E(e2e.BloomerpE2ETestCase):
    browser_context_options = {"viewport": {"width": 1440, "height": 1000}}

    def prepare_workflow(self):
        self.workflow = Workflow.objects.create(name="Canvas interactions")
        self.first = WorkflowNode.objects.create(
            workflow=self.workflow, type="ACTION", sub_type="SEND_USER_MESSAGE",
            name="First message", parameters={"users": [self.admin_user.pk], "message": "Hello", "message_type": "success"},
            pos_x=0, pos_y=0,
        )
        self.second = WorkflowNode.objects.create(
            workflow=self.workflow, type="ACTION", sub_type="SEND_USER_MESSAGE",
            name="Second message", parameters={"users": [self.admin_user.pk], "message": "World", "message_type": "success"},
            pos_x=360, pos_y=0,
        )
        WorkflowEdge.objects.create(from_node=self.first, to_node=self.second)

    def get_test_scenarios(self):
        return [
            e2e.E2ERequestScenario(
                name=name, user=self.admin_user, prepare=self.prepare_workflow,
                url=lambda: f"/automation/workflows/{self.workflow.pk}/builder/",
                actions=[e2e.E2EAction(name=name, execute=callback)],
            )
            for name, callback in [
                ("Selection, rename, duplicate and delete", self.selection_actions),
                ("Directional selection, group movement and clipboard", self.keyboard_actions),
                ("Rectangle selection, group drag and touchpad panning", self.pointer_actions),
                ("Edge selection and renaming", self.edge_actions),
                ("Add Node backdrop covers the app sidebar", self.drawer_overlay),
                ("Canvas fills a narrow detail view", self.canvas_layout),
                ("Double-click edits configuration", self.edit_configuration),
                ("Leaving the builder saves pending movement", self.save_on_navigation),
            ]
        ]

    def nodes(self):
        return self.page.locator("#drawflow .drawflow-node")

    def selected(self):
        return self.page.locator("#drawflow .drawflow-node.workflow-selected")

    def ready(self):
        expect(self.nodes()).to_have_count(2)
        self.page.locator("#zoom-out-btn").click()
        self.page.locator("#zoom-out-btn").click()

    def selection_actions(self):
        self.ready()
        self.nodes().first.click()
        expect(self.selected()).to_have_count(1)
        self.page.get_by_role("button", name="Rename", exact=True).click()
        name = self.page.get_by_role("textbox", name="Node name", exact=True)
        name.fill("Renamed message")
        name.press("ArrowLeft")
        expect(self.nodes()).to_have_count(2)
        name.press("Enter")
        expect(self.nodes().first).to_contain_text("Renamed message")
        self.page.get_by_role("button", name="Duplicate", exact=True).click()
        expect(self.nodes()).to_have_count(3)
        expect(self.selected()).to_have_count(1)
        self.page.get_by_role("button", name="Delete", exact=True).click()
        expect(self.nodes()).to_have_count(2)
        expect(self.page.locator("[data-selection-actions]")).to_be_hidden()
        self.nodes().first.click(button="right")
        expect(self.page.get_by_role("textbox", name="Node name", exact=True)).to_be_visible()
        self.page.keyboard.press("Escape")

    def keyboard_actions(self):
        self.ready()
        self.nodes().first.click()
        self.page.keyboard.press("Control+Alt+ArrowRight")
        expect(self.nodes().nth(1)).to_have_class(re.compile("workflow-selected"))
        self.page.keyboard.press("Control+Alt+Shift+ArrowLeft")
        expect(self.selected()).to_have_count(2)
        expect(self.page.locator(".connection.workflow-selected")).to_have_count(1)
        before = [node.bounding_box() for node in self.nodes().all()]
        self.page.keyboard.press("Shift+ArrowDown")
        after = [node.bounding_box() for node in self.nodes().all()]
        for old, new in zip(before, after):
            self.assertGreater(new["y"], old["y"])
        for modifier in ("Control", "Meta"):
            self.page.keyboard.press(f"{modifier}+c")
            self.page.keyboard.press(f"{modifier}+v")
            expect(self.nodes()).to_have_count(4)
            expect(self.selected()).to_have_count(2)
            expect(self.page.locator(".connection")).to_have_count(2)
            self.page.keyboard.press("Delete")
            expect(self.nodes()).to_have_count(2)
            self.nodes().first.click()
            self.page.keyboard.press("Control+Alt+Shift+ArrowRight")
        width = self.nodes().first.bounding_box()["width"]
        self.page.keyboard.press("Meta+=")
        self.assertGreater(self.nodes().first.bounding_box()["width"], width)
        self.page.keyboard.press("Control+-")
        self.assertAlmostEqual(self.nodes().first.bounding_box()["width"], width, delta=1)

    def pointer_actions(self):
        self.ready()
        boxes = [node.bounding_box() for node in self.nodes().all()]
        left, top = min(b["x"] for b in boxes) - 15, min(b["y"] for b in boxes) - 15
        right = max(b["x"] + b["width"] for b in boxes) + 15
        bottom = max(b["y"] + b["height"] for b in boxes) + 15
        self.page.mouse.move(left, top)
        self.page.mouse.down()
        self.page.mouse.move(right, bottom, steps=10)
        self.page.mouse.up()
        expect(self.selected()).to_have_count(2)
        expect(self.page.locator(".connection.workflow-selected")).to_have_count(1)
        self.page.mouse.move(boxes[0]["x"] + 40, boxes[0]["y"] + 30)
        self.page.mouse.down()
        self.page.mouse.move(boxes[0]["x"] + 90, boxes[0]["y"] + 60, steps=5)
        self.page.mouse.up()
        for old, node in zip(boxes, self.nodes().all()):
            self.assertAlmostEqual(node.bounding_box()["x"] - old["x"], 50, delta=2)
            self.assertAlmostEqual(node.bounding_box()["y"] - old["y"], 30, delta=2)
        before = self.nodes().first.bounding_box()
        self.page.mouse.wheel(80, 60)
        self.page.wait_for_function("""x => document.querySelector('.drawflow-node').getBoundingClientRect().x < x""", arg=before["x"])
        self.assertAlmostEqual(self.nodes().first.bounding_box()["x"], before["x"] - 80, delta=2)

    def edge_actions(self):
        self.ready()
        # Read geometry only; all interactions use mouse/keyboard events.
        point = self.page.locator(".connection .main-path").evaluate("""path => {
            const point = path.getPointAtLength(path.getTotalLength() / 2).matrixTransform(path.getScreenCTM());
            return {x: point.x, y: point.y};
        }""")
        self.page.mouse.click(point["x"], point["y"])
        expect(self.page.locator(".connection.workflow-selected")).to_have_count(1)
        expect(self.page.get_by_role("button", name="Duplicate", exact=True)).to_be_hidden()
        self.page.get_by_role("button", name="Rename", exact=True).click()
        self.page.get_by_role("textbox", name="Edge name", exact=True).fill("Next step")
        self.page.keyboard.press("Control+Enter")
        expect(self.page.locator("[data-workflow-edge-label]")).to_have_text("Next step")
        self.page.locator("[data-workflow-edge-label]").click()
        self.page.keyboard.press("Backspace")
        expect(self.page.locator(".connection")).to_have_count(0)
        expect(self.nodes()).to_have_count(2)

    def canvas_layout(self):
        self.page.set_viewport_size({"width": 952, "height": 998})
        overlay = self.page.locator("#sidebar-overlay")
        if overlay.is_visible():
            overlay.click(position={"x": 900, "y": 300})
            expect(overlay).to_be_hidden()
        self.ready()
        canvas = self.page.locator("#drawflow").bounding_box()
        content = self.page.locator("#detail-view-content").bounding_box()
        toolbar = self.page.locator(".workflow-toolbar").bounding_box()
        self.assertAlmostEqual(canvas["x"], content["x"], delta=1)
        self.assertAlmostEqual(canvas["width"], content["width"], delta=1)
        self.assertGreater(toolbar["y"], canvas["y"])
        self.assertLess(toolbar["y"] + toolbar["height"], canvas["y"] + canvas["height"])
        self.assertLessEqual(canvas["y"] + canvas["height"], 998)

    def edit_configuration(self):
        self.ready()
        self.nodes().first.dblclick()
        expect(self.page.locator('form[data-workflow-node-config-form="true"]')).to_be_visible()

    def save_on_navigation(self):
        self.ready()
        first = self.nodes().first
        first.click()
        previous_top = first.evaluate("node => parseFloat(node.style.top)")
        self.page.keyboard.press("Shift+ArrowDown")
        moved_top = first.evaluate("node => parseFloat(node.style.top)")
        self.assertGreater(moved_top, previous_top)
        with self.page.expect_response(lambda response: "/components/automation/save_workflow/" in response.url and response.request.method == "POST") as saved:
            self.page.get_by_role("tab", name="Details", exact=True).click()
        self.assertEqual(saved.value.status, 200, saved.value.headers.get("location", "No redirect location"))
        self.page.get_by_role("tab", name="Builder", exact=True).click()
        expect(self.nodes()).to_have_count(2)
        self.assertAlmostEqual(self.nodes().first.evaluate("node => parseFloat(node.style.top)"), moved_top, delta=1)

    def drawer_overlay(self):
        self.ready()
        self.page.get_by_role("button", name="Add Node", exact=True).click()
        drawer = self.page.locator("#node-drawer")
        expect(drawer).to_be_visible()
        self.assertTrue(self.page.evaluate("document.elementFromPoint(20, 30)?.id === 'node-drawer'"))
        # A click over the app sidebar must close the drawer instead of opening navigation.
        self.page.mouse.click(20, 30)
        expect(drawer).to_be_hidden()
        self.page.get_by_role("button", name="Add Node", exact=True).click()
        expect(drawer).to_be_visible()
        drawer.locator('[data-node-subtype-id="SEND_USER_MESSAGE"]').click()
        expect(self.nodes()).to_have_count(3)
        expect(drawer).to_be_hidden()


class TestWorkflowConnectionGeometryE2E(TestWorkflowBuilderE2E):
    def get_test_scenarios(self):
        return [e2e.E2ERequestScenario(
            name="Connections stay attached after closing node configuration",
            user=self.admin_user, prepare=self.prepare_workflow,
            url=lambda: f"/automation/workflows/{self.workflow.pk}/builder/",
            actions=[e2e.E2EAction(execute=self.connection_geometry)],
        )]

    def assert_connections_attached(self):
        expect(self.page.locator("#drawflow .connection")).to_have_count(1)
        # Read rendered SVG endpoints; interactions never call editor internals.
        self.page.wait_for_function("""() => {
            const canvas = document.querySelector('#drawflow');
            return [...canvas.querySelectorAll('.connection')].every(edge => {
                const classes = [...edge.classList];
                const source = classes.find(c => c.startsWith('node_out_node-')).replace('node_out_', '');
                const target = classes.find(c => c.startsWith('node_in_node-')).replace('node_in_', '');
                const output = classes.find(c => c.startsWith('output_'));
                const input = classes.find(c => c.startsWith('input_'));
                const path = edge.querySelector('.main-path');
                const start = path.getPointAtLength(0).matrixTransform(path.getScreenCTM());
                const end = path.getPointAtLength(path.getTotalLength()).matrixTransform(path.getScreenCTM());
                const a = canvas.querySelector(`#${source} .${output}`).getBoundingClientRect();
                const b = canvas.querySelector(`#${target} .${input}`).getBoundingClientRect();
                return Math.hypot(start.x - a.x - a.width / 2, start.y - a.y - a.height / 2) < 2
                    && Math.hypot(end.x - b.x - b.width / 2, end.y - b.y - b.height / 2) < 2;
            });
        }""")

    def connection_geometry(self):
        self.ready()
        width = self.nodes().first.bounding_box()["width"]
        self.nodes().first.click(button="right")
        name = self.page.get_by_role("textbox", name="Node name", exact=True)
        name.fill("A renamed message node with a much wider title")
        name.press("Enter")
        self.assertGreater(self.nodes().first.bounding_box()["width"], width)
        self.nodes().first.click()
        self.page.keyboard.press("ArrowRight")
        self.assert_connections_attached()
        modal = self.page.locator('#bloomerp-general-use-modal')
        for edit_message in (False, True):
            self.nodes().first.dblclick()
            form = modal.locator('form[data-workflow-node-config-form="true"]')
            expect(form).to_be_visible()
            if edit_message:
                form.locator('[name="message"]').fill("A much longer message changes the width of the node's configuration preview")
                form.locator('[name="message_type"]').focus()
            modal.locator('[bloomerp-close-modal]').first.click()
            expect(modal).to_be_hidden()
            if edit_message:
                expect(self.nodes().first).to_contain_text("A much longer message")
            self.assert_connections_attached()


class TestWorkflowModalInitializationE2E(TestWorkflowConnectionGeometryE2E):
    browser_context_options = {
        "viewport": {"width": 1440, "height": 1000}, "color_scheme": "dark",
    }

    def prepare_workflow(self):
        super().prepare_workflow()
        self.first.type = "TRIGGER"
        self.first.sub_type = "HUMAN_TRIGGER"
        self.first.parameters = {"data": {}}
        self.first.save()

    def connection_geometry(self):
        # Start fresh and open a JSON editor, whose lazy imports must not boot
        # the application a second time through an unversioned bundle URL.
        self.page.reload()
        expect(self.nodes()).to_have_count(2)
        self.nodes().first.dblclick()
        modal = self.page.locator('#bloomerp-general-use-modal')
        expect(modal.locator('.ace_editor.ace-tomorrow-night')).to_be_visible()
        modal.locator('[bloomerp-close-modal]').first.click()
        expect(modal).to_be_hidden()
        expect(self.page.locator('#drawflow > .drawflow')).to_have_count(1)
        expect(self.nodes()).to_have_count(2)
        self.assert_connections_attached()
