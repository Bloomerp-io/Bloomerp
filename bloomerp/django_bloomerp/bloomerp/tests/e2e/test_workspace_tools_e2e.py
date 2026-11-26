from playwright.sync_api import Locator, expect

from bloomerp.tests.base import E2EAction, E2ERequestScenario, e2e_test_case


class TestWorkspaceToolsE2E(e2e_test_case.BloomerpE2ETestCase):
    """Exercise the persistent Agent and Chat controls across tool switches."""

    auto_create_customers = False
    browser_context_options = {"viewport": {"width": 1364, "height": 998}}

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Cover shortcut navigation, panel dismissal, retained drafts and placement."""
        return [
            E2ERequestScenario(
                name="Keyboard sequences open the workspace tools",
                user=self.admin_user,
                url="/",
                actions=[
                    E2EAction(
                        name="Open all three existing launchers with ordered keys",
                        execute=self.assert_tool_shortcuts,
                    ),
                    E2EAction(
                        name="Cancel sequences in the composer, with Escape, and after a pause",
                        execute=self.assert_shortcut_cancellation,
                    ),
                    E2EAction(
                        name="Keep both modified global search shortcuts available",
                        execute=self.assert_search_shortcuts,
                    ),
                ],
            ),
            E2ERequestScenario(
                name="Footer tools switch panels and preserve the agent draft",
                user=self.admin_user,
                url="/",
                actions=[
                    E2EAction(
                        name="Toggle tools and restore their state after refresh",
                        execute=self.assert_tool_switching,
                    ),
                ],
            ),
            E2ERequestScenario(
                name="Mobile dark footer ignores former floating positions",
                user=self.admin_user,
                prepare=self.prepare_mobile,
                url="/",
                actions=[
                    E2EAction(
                        name="Keep tools and panels above the bottom viewport edge",
                        execute=self.assert_mobile_tools,
                    ),
                ],
            ),
        ]

    def launcher(self, panel_id: str) -> Locator:
        """Find a footer control by the panel it owns."""
        return self.page.locator(
            f'[data-floating-panel-launcher][aria-controls="{panel_id}"]'
        )

    def assert_tool_shortcuts(self) -> None:
        """Check the hints, accessible descriptions, and real launcher actions."""
        for key, panel_id in (
            ("a", "bloomerp-agent-panel"),
            ("p", "bloomerp-pages-panel"),
            ("c", "im-messaging-panel"),
        ):
            launcher = self.launcher(panel_id)
            panel = self.page.locator(f"#{panel_id}")
            label = f"K → {key.upper()}"
            expect(launcher).to_have_accessible_description(
                f"Keyboard shortcut: K then {key.upper()}"
            )
            self.assertIsNone(launcher.get_attribute("aria-keyshortcuts"))
            launcher.focus()
            expect(launcher.locator("xpath=..").get_by_text(label, exact=True)).to_be_visible()
            self.page.keyboard.press(key)
            expect(panel).to_be_hidden()
            self.page.keyboard.press("k")
            self.page.keyboard.press(key)
            expect(panel).to_be_visible()
            launcher.click()
            expect(panel).to_be_hidden()

    def assert_shortcut_cancellation(self) -> None:
        """Keep letters available to the composer and discard interrupted prefixes."""
        agent = self.launcher("bloomerp-agent-panel")
        chat = self.launcher("im-messaging-panel")
        chat_panel = self.page.locator("#im-messaging-panel")
        composer = self.page.locator(
            '#bloomerp-agent-panel [data-agent-composer] [contenteditable="true"]'
        )
        agent.click()
        composer.focus()
        self.page.keyboard.press("k")
        self.page.keyboard.press("c")
        expect(composer).to_have_text("kc")
        expect(chat_panel).to_be_hidden()

        chat.focus()
        self.page.keyboard.press("k")
        composer.focus()
        chat.focus()
        self.page.keyboard.press("c")
        expect(chat_panel).to_be_hidden()

        self.page.keyboard.down("k")
        self.page.keyboard.press("Escape")
        self.page.keyboard.down("k")
        self.page.keyboard.up("k")
        self.page.keyboard.press("c")
        expect(chat_panel).to_be_hidden()

        self.page.keyboard.press("k")
        self.page.wait_for_timeout(1100)
        self.page.keyboard.press("c")
        expect(chat_panel).to_be_hidden()
        agent.click()

    def assert_search_shortcuts(self) -> None:
        """Open the existing general and route-only global search modes."""
        search = self.page.locator("#global-search-modal-input")
        self.page.keyboard.press("ControlOrMeta+k")
        expect(search).to_be_focused()
        expect(search).to_have_value("")
        self.page.keyboard.press("Escape")
        expect(search).to_be_hidden()
        self.page.keyboard.press("ControlOrMeta+Shift+k")
        expect(search).to_be_focused()
        expect(search).to_have_value(">")

    def assert_footer_layout(self) -> None:
        """Keep no gap above the controls while preserving their right inset."""
        footer = self.page.get_by_role("group", name="Workspace tools")
        expect(footer).to_be_visible()
        expect(self.launcher("bloomerp-agent-panel")).to_have_text("Agent")
        expect(self.launcher("im-messaging-panel")).to_contain_text("Chat")
        footer_box = footer.bounding_box()
        main_box = self.page.locator("#main").bounding_box()
        self.assertIsNotNone(footer_box)
        self.assertIsNotNone(main_box)
        self.assertAlmostEqual(
            main_box["y"] + main_box["height"], footer_box["y"], delta=1
        )
        viewport = self.page.viewport_size
        self.assertLessEqual(footer_box["y"] + footer_box["height"], viewport["height"])
        self.assertAlmostEqual(
            footer_box["x"] + footer_box["width"], viewport["width"] - 12, delta=1
        )

    def assert_tool_switching(self) -> None:
        """Keep one panel open while retaining drafts and accessible toggle state."""
        self.assert_footer_layout()
        agent = self.launcher("bloomerp-agent-panel")
        chat = self.launcher("im-messaging-panel")
        agent_panel = self.page.locator("#bloomerp-agent-panel")
        chat_panel = self.page.locator("#im-messaging-panel")
        draft = agent_panel.locator("[data-agent-input]")

        agent.click()
        expect(agent_panel).to_be_visible()
        expect(agent).to_be_visible()
        expect(agent).to_have_attribute("aria-expanded", "true")
        draft.fill("Help me plan tomorrow")

        chat.click()
        expect(agent_panel).to_be_hidden()
        expect(agent).to_have_attribute("aria-expanded", "false")
        expect(chat_panel).to_be_visible()
        expect(chat_panel.locator("[data-search]")).to_be_focused()
        self.page.keyboard.press("Escape")
        expect(chat_panel).to_be_hidden()
        expect(chat).to_be_focused()
        expect(chat).to_have_attribute("aria-expanded", "false")

        chat.press("Enter")
        expect(chat_panel).to_be_visible()
        chat.click()
        expect(chat_panel).to_be_hidden()
        chat.click()
        self.page.reload(wait_until="domcontentloaded")
        expect(chat_panel).to_be_visible()
        expect(chat).to_have_attribute("aria-expanded", "true")
        expect(agent_panel).to_be_hidden()

        agent.click()
        expect(chat_panel).to_be_hidden()
        expect(draft).to_have_text("Help me plan tomorrow")
        agent_panel.get_by_role("button", name="Close assistant").click()
        expect(agent_panel).to_be_hidden()
        expect(agent).to_be_focused()

    def prepare_mobile(self) -> None:
        """Use a narrow dark viewport with old draggable locations still stored."""
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.emulate_media(color_scheme="dark")
        self.context.add_init_script(
            f"localStorage.setItem('bloomerp_agent_launcher_{self.admin_user.pk}', "
            "JSON.stringify({x: 30, y: 100}));"
            "localStorage.setItem('bloomerp-im-draft-position', "
            "JSON.stringify({x: 90, y: 150}));"
        )

    def assert_mobile_tools(self) -> None:
        """Ensure each mobile panel stays inside the viewport above its controls."""
        expect(self.page.locator("html")).to_have_attribute("data-theme", "dark")
        self.assert_footer_layout()
        footer_box = self.page.locator(".workspace-tools").bounding_box()
        for panel_id in ("bloomerp-agent-panel", "im-messaging-panel"):
            button = self.launcher(panel_id)
            button.click()
            panel = self.page.locator(f"#{panel_id}")
            expect(panel).to_be_visible()
            expect(button).to_be_visible()
            box = panel.bounding_box()
            self.assertIsNotNone(box)
            self.assertGreaterEqual(box["x"], 0)
            self.assertGreaterEqual(box["y"], 0)
            self.assertLessEqual(box["x"] + box["width"], 390)
            self.assertLessEqual(box["y"] + box["height"], footer_box["y"])
            button.click()
            expect(panel).to_be_hidden()
