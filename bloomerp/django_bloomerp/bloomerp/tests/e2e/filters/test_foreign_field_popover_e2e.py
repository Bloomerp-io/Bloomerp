"""Native top-layer regression tests using production FK and dropdown components.

These isolated browser fixtures follow test_filter_container_e2e.py: no Django
server or database is needed, and every HTTP request is intercepted locally.
"""
from pathlib import Path
import subprocess
import unittest
from urllib.parse import urlparse

from playwright.sync_api import Route, expect, sync_playwright


class TestForeignFieldPopoverE2E(unittest.TestCase):
    """Exercise rendering-layer behavior that a DOM emulator cannot validate."""

    @classmethod
    def setUpClass(cls) -> None:
        """Bundle production components and launch a real Chromium instance."""
        static_src = Path(__file__).resolve().parents[3] / 'static_src'
        entry = '''
            import Alpine from 'alpinejs';
            import ForeignFieldWidget from './ts/components/widgets/ForeignFieldWidget';
            import DropdownKeyboard from './ts/components/DropdownKeyboard';
            /** Initialize the real widget and its containing dropdown keyboard controller. */
            function initializeFixture(): void {
                const root = document.querySelector<HTMLElement>('#widget')!;
                const widget = new ForeignFieldWidget(root);
                widget.initialize();
                const keyboard = new DropdownKeyboard(document.querySelector<HTMLElement>('#filter')!);
                keyboard.initialize();
                Object.assign(window, { widget, dropdownKeyboard: keyboard });
                Alpine.start();
            }
            initializeFixture();
        '''
        result = subprocess.run(
            [str(static_src / 'node_modules/.bin/esbuild'), '--bundle', '--format=iife',
             '--loader=ts', '--tsconfig=tsconfig.json', '--loader:.css=empty'],
            cwd=static_src, input=entry, text=True, capture_output=True, check=True,
        )
        cls.bundle = result.stdout
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(headless=True)
        except Exception:
            cls.playwright.stop()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        """Release the shared browser and Playwright driver."""
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self) -> None:
        """Provide an isolated page with real Alpine click-away and native popover."""
        self.context = self.browser.new_context(viewport={'width': 1100, 'height': 800})
        self.page = self.context.new_page()
        self.page.route('http://localhost/**', self.respond)
        self.page.goto('http://localhost/')
        self.page.add_script_tag(content=self.bundle)
        self.menu = self.page.locator('.foreign-field-dropdown')
        self.input = self.page.get_by_label('Related object')
        self.panel = self.page.locator('#panel')

    def tearDown(self) -> None:
        """Discard each fixture, including all widget listeners and requests."""
        self.context.close()

    def respond(self, route: Route) -> None:
        """Serve only deterministic HTML and FK lookup data without external access."""
        path = urlparse(route.request.url).path
        if path.startswith('/components/search-objects/'):
            route.fulfill(json={'objects': [
                {'id': 1, 'string_representation': 'Ada', 'detail_url': ''},
                {'id': 2, 'string_representation': 'Grace', 'detail_url': ''},
            ]})
        elif path == '/':
            route.fulfill(content_type='text/html', body='''<!doctype html><html><head>
                <style>
                    * { box-sizing: border-box; }
                    body { margin: 0; min-height: 1600px; font: 16px sans-serif; }
                    .hidden { display: none !important; }
                    #filter { margin: 30px; }
                    #panel { position: fixed; inset: auto; left: 240px; top: 140px;
                        width: 440px; height: 260px; padding: 24px; margin: 0;
                        border: 3px solid #777; overflow: visible; background: white; }
                    #widget, .input-wrap { position: relative; }
                    input { width: 220px; height: 36px; }
                    .foreign-field-dropdown { position: absolute; left: 0; right: 0;
                        top: 100%; margin-top: 4px; z-index: 50; }
                    .foreign-field-results { background: white; margin: 0; padding: 0;
                        list-style: none; border: 1px solid #333; }
                    .foreign-field-results li, [data-action] { padding: 10px; background: white; }
                    #outside { position: fixed; left: 10px; bottom: 10px; }
                </style></head><body>
                <div id="filter" x-data="{ open: false }"
                    x-effect="open ? $refs.panel.showPopover() : $refs.panel.hidePopover()"
                    @click.away="open = false" @dropdown-dismiss="open = false"
                    @keydown.escape.window="if (!$event.defaultPrevented) open = false">
                    <button id="trigger" aria-haspopup="true" @click="open = !open">Filter</button>
                    <div id="panel" x-ref="panel" popover="manual" data-dropdown-panel
                        :aria-hidden="(!open).toString()">
                        <div id="widget" bloomerp-component="foreign-field-widget"
                            data-content-type-id="1" data-field-name="related" data-is-m2m="false">
                            <div class="input-wrap"><input type="text" aria-label="Related object">
                                <div class="foreign-field-dropdown hidden">
                                    <ul class="foreign-field-results"></ul>
                                    <div data-action="create-new" tabindex="0">Create new</div>
                                    <div data-action="advanced-query" tabindex="0">Advanced query</div>
                                </div>
                            </div><div class="foreign-field-selected"></div>
                        </div>
                        <button id="after">After field</button>
                    </div>
                </div><button id="outside">Outside</button></body></html>''')
        else:
            route.fulfill(status=404, body='Unexpected fixture request')

    def open_results(self) -> None:
        """Open the filter and fetch FK choices through a genuine focus event."""
        self.page.get_by_role('button', name='Filter', exact=True).click()
        self.input.click()
        expect(self.menu.locator('li')).to_have_count(2)
        expect(self.menu).to_be_visible()

    def assert_anchored(self) -> None:
        """Check real rendered coordinates and hit-testing rather than z-index alone."""
        input_box = self.input.bounding_box()
        menu_box = self.menu.bounding_box()
        self.assertIsNotNone(input_box)
        self.assertIsNotNone(menu_box)
        self.assertAlmostEqual(menu_box['x'], input_box['x'], delta=1)
        self.assertAlmostEqual(menu_box['y'], input_box['y'] + input_box['height'] + 4, delta=1)
        self.assertAlmostEqual(menu_box['width'], input_box['width'], delta=1)
        self.assertTrue(self.menu.locator('li').first.evaluate('''element => {
            const rect = element.getBoundingClientRect();
            return element.contains(document.elementFromPoint(rect.left + rect.width / 2,
                rect.top + rect.height / 2));
        }'''))

    def test_results_are_clickable_above_filter_and_keep_it_open(self) -> None:
        """Select a hit-testable FK result without triggering Alpine click-away."""
        self.open_results()
        self.assert_anchored()
        self.menu.get_by_text('Ada', exact=True).click()
        self.assertTrue(self.panel.evaluate("element => element.matches(':popover-open')"))
        expect(self.page.locator('#widget input[type=hidden][name=related]')).to_have_value('1')
        expect(self.menu).to_be_hidden()

    def test_scaled_panel_resize_scroll_and_destroy(self) -> None:
        """Keep scaled coordinates correct and restore the menu when destroyed."""
        self.panel.evaluate("element => element.style.transform = 'scale(0.95)'")
        self.open_results()
        self.assert_anchored()
        self.page.set_viewport_size({'width': 1000, 'height': 700})
        self.page.evaluate('window.scrollTo(0, 100)')
        self.assert_anchored()
        self.page.evaluate('window.widget.destroy()')
        self.assertTrue(self.menu.evaluate("element => element.parentElement.classList.contains('input-wrap')"))
        self.assertEqual(self.menu.get_attribute('style'), '')
        self.panel.evaluate('element => element.hidePopover()')
        expect(self.menu).to_be_hidden()

    def test_keyboard_escape_outside_click_and_reopen(self) -> None:
        """Dismiss only FK choices with Escape and retain correct Tab traversal."""
        self.open_results()
        self.input.press('Tab')
        expect(self.menu.locator('li').first).to_be_focused()
        self.page.keyboard.press('Tab')
        expect(self.menu.locator('li').nth(1)).to_be_focused()
        self.page.keyboard.press('Shift+Tab')
        expect(self.menu.locator('li').first).to_be_focused()
        self.page.keyboard.press('Escape')
        expect(self.menu).to_be_hidden()
        expect(self.input).to_be_focused()
        self.assertTrue(self.panel.evaluate("element => element.matches(':popover-open')"))
        self.input.fill('Ada')
        expect(self.menu).to_be_visible()
        self.page.get_by_role('button', name='Outside', exact=True).click()
        expect(self.menu).to_be_hidden()
        self.assertFalse(self.panel.evaluate("element => element.matches(':popover-open')"))
        self.open_results()
        self.assert_anchored()

    def test_ordinary_widget_in_nested_modal_keeps_body_portal(self) -> None:
        """Preserve the ordinary body portal and its containing nested form values."""
        self.page.evaluate('''() => {
            const outer = document.createElement('div');
            outer.setAttribute('bloomerp-component', 'modal');
            outer.style.cssText = 'position:fixed;inset:80px;z-index:100;background:white';
            outer.innerHTML = '<input id="parent-value" value="Keep me">';
            const inner = document.createElement('div');
            inner.setAttribute('bloomerp-component', 'modal');
            inner.style.cssText = 'position:fixed;left:260px;top:180px;width:400px;z-index:200;overflow:hidden';
            inner.append(document.querySelector('#widget'));
            outer.append(inner);
            document.body.append(outer);
        }''')
        self.input.click()
        expect(self.menu.locator('li')).to_have_count(2)
        self.assertTrue(self.menu.evaluate('element => element.parentElement === document.body'))
        self.assert_anchored()
        self.menu.get_by_text('Grace', exact=True).click()
        expect(self.page.locator('#widget input[type=hidden][name=related]')).to_have_value('2')
        expect(self.page.locator('#parent-value')).to_have_value('Keep me')
