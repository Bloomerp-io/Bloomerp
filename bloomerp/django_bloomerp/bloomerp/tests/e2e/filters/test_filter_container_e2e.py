"""Browser contract tests for the editor; discovery responses are fixture data."""
import json
from pathlib import Path
import subprocess
import unittest

from playwright.sync_api import sync_playwright, expect


class TestFilterContainerE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        static_src = Path(__file__).resolve().parents[3] / 'static_src'
        entry = '''
            import FilterContainer from './ts/components/filters/FilterContainer';
            import WorkspaceContainer from './ts/components/workspaces/WorkspaceContainer';
            import { registerComponent } from './ts/components/BaseComponent';
            import { BaseWidget } from './ts/components/widgets/BaseWidget';
            class StructuredWidget extends BaseWidget {
                getValue() { return JSON.parse(this.element.querySelector('textarea').value); }
                setValue(value) { this.element.querySelector('textarea').value = JSON.stringify(value); }
            }
            registerComponent('test-structured-widget', StructuredWidget);
            window.startWorkspace = () => {
                const workspace = document.createElement('div');
                workspace.dataset.workspaceId = '42';
                workspace.dataset.layoutRenderItemUrl = '/tile';
                workspace.dataset.layout = JSON.stringify({rows: [{columns: 1, items: [{id: '7', colspan: 1}]}]});
                document.body.append(workspace);
                workspace.innerHTML = '<div data-layout-root><div data-layout-row><div data-layout-grid><div bloomerp-component="workspace-tile" data-layout-item-id="7">Initial tile</div></div></div></div>';
                const root = document.querySelector('#filters');
                root.dataset.scope = 'workspace';
                root.dataset.scopeId = '42';
                workspace.prepend(root);
                const component = new WorkspaceContainer(workspace);
                component.initialize();
                window.workspaceComponent = component;
            };

            window.startFilters = (initial) => {
                const root = document.querySelector('#filters');
                root.dataset.initialFilters = JSON.stringify(initial);
                const component = new FilterContainer(root);
                component.initialize();
                window.filterComponent = component;
                root.addEventListener('bloomerp:filters-apply', event => window.applied = event.detail.filters);
            };
        '''
        result = subprocess.run(
            [str(static_src / 'node_modules/.bin/esbuild'), '--bundle', '--format=iife', '--tsconfig=tsconfig.json', '--loader:.css=empty'],
            cwd=static_src, input=entry, text=True, capture_output=True, check=True,
        )
        cls.bundle = result.stdout
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.page.route('http://localhost/**', self.respond)
        self.page.goto('http://localhost/')
        self.page.add_script_tag(content=self.bundle)

    def tearDown(self):
        self.context.close()

    def respond(self, route):
        from urllib.parse import urlparse, parse_qs
        url = urlparse(route.request.url)
        params = parse_qs(url.query)
        if url.path == '/':
            route.fulfill(content_type='text/html', body='''<div id="filters" data-scope="model" data-scope-id="1"
                data-fields-url="/fields" data-lookups-url="/lookups" data-value-editor-url="/editor"></div>''')
            return
        if url.path == '/tile':
            route.fulfill(content_type='text/html', body='<div bloomerp-component="workspace-tile" data-layout-item-id="7">Refreshed tile</div>')
            return
        if url.path == '/fields':
            fields = [{'field': 'name', 'label': 'Name'}] if 'field_path' in params else [
                {'field': 'name', 'label': 'Name'}, {'field': 'relation', 'label': 'Relation'},
                {'field': 'structured', 'label': 'Structured'},
            ]
            if params.get('scope') == ['workspace']:
                fields = [{**field, 'field': 'tile_7:' + field['field']} for field in fields]
            payload = [{'name': 'Fields', 'fields': fields}]
        elif url.path == '/lookups':
            payload = [{'id': 'traverse', 'label': 'Explore', 'nested': True}] if params['field_path'] == ['relation'] else [
                {'id': 'compare', 'label': 'Matches', 'nested': False},
            ]
        else:
            data = route.request.post_data_json
            if data['field_path'] == 'structured':
                widget = '<div bloomerp-component="test-structured-widget"><textarea aria-label="Structured value">null</textarea></div>'
            else:
                from html import escape
                widget = '<input class="input w-full" name="value" aria-label="Value" value="' + escape(str(data.get('value', '')), quote=True) + '">'
            payload = {'widget': widget}
        route.fulfill(json=payload)

    def start(self, groups=None):
        self.page.evaluate('groups => window.startFilters(groups)', groups or [])

    def add_name_condition(self, value):
        row = self.page.locator('[data-filter-condition]').last
        row.get_by_label('Field', exact=True).select_option(label='Name')
        row.get_by_label('Lookup', exact=True).select_option(label='Matches')
        row.get_by_label('Value', exact=True).fill(value)

    def test_multiple_conditions_and_groups(self):
        """
        UC: Build an OR group and a second group using the editor controls.
        Expected Result: Apply emits two canonical groups in order.
        """
        # 1. Build alternatives in the first group.
        self.start()
        self.add_name_condition('David')
        self.page.get_by_label('Match conditions').select_option('OR')
        self.page.get_by_role('button', name='Add condition', exact=True).click()
        self.add_name_condition('Kyle')
        # 2. Add another group and apply.
        self.page.get_by_role('button', name='Add group', exact=True).click()
        self.add_name_condition('David')
        self.page.get_by_role('button', name='Apply filters').click()
        groups = self.page.evaluate('window.applied')
        self.assertEqual([group['connector'] for group in groups], ['OR', 'AND'])
        self.assertEqual([item['value'] for item in groups[0]['conditions']], ['David', 'Kyle'])
        self.assertEqual(groups[1]['conditions'][0]['lookup_id'], 'compare')

    def test_restore_nested_condition(self):
        """
        UC: Open a saved condition that traverses a relation.
        Expected Result: Both field levels and the terminal value are restored.
        """
        # 1. Restore a nested path using metadata-only lookup IDs.
        groups = [{'connector': 'AND', 'conditions': [{'field_path': 'relation__name', 'lookup_id': 'compare', 'value': 'Belgium'}]}]
        self.start(groups)
        expect(self.page.get_by_label('Value', exact=True)).to_have_value('Belgium')
        expect(self.page.get_by_label('Field', exact=True)).to_have_count(2)
        # 2. Apply the restored condition unchanged.
        self.page.get_by_role('button', name='Apply filters').click()
        self.assertEqual(self.page.evaluate('window.applied'), groups)

    def test_component_widget_round_trip(self):
        """
        UC: Restore and read a component widget containing structured values.
        Expected Result: BaseWidget methods preserve objects, arrays, booleans, and numbers.
        """
        # 1. Restore through the widget setter.
        value = [{'id': 3, 'active': False}]
        groups = [{'connector': 'OR', 'conditions': [{'field_path': 'structured', 'lookup_id': 'compare', 'value': value}]}]
        self.start(groups)
        expect(self.page.get_by_label('Structured value')).to_have_value(json.dumps(value, separators=(',', ':')))
        # 2. Read through the widget getter.
        self.page.get_by_role('button', name='Apply filters').click()
        self.assertEqual(self.page.evaluate('window.applied'), groups)

    def test_incomplete_condition_cannot_apply(self):
        """
        UC: Apply a group before selecting a field and lookup.
        Expected Result: Feedback is visible and no apply event is emitted.
        """
        # 1. Open the initial incomplete condition.
        self.start()
        # 2. Attempt to apply it.
        self.page.get_by_role('button', name='Apply filters').click()
        expect(self.page.get_by_text('Complete every filter condition before applying.')).to_be_visible()
        self.assertIsNone(self.page.evaluate('window.applied'))

    def test_clear_then_apply(self):
        """
        UC: Clear a saved filter and apply the empty editor.
        Expected Result: The emitted filter list is empty.
        """
        # 1. Restore a condition and clear it.
        self.start([{'connector': 'AND', 'conditions': [{'field_path': 'name', 'lookup_id': 'compare', 'value': 'David'}]}])
        expect(self.page.get_by_label('Value', exact=True)).to_have_value('David')
        self.page.get_by_role('button', name='Clear', exact=True).click()
        # 2. Apply the empty list.
        self.page.get_by_role('button', name='Apply filters').click()
        self.assertEqual(self.page.evaluate('window.applied'), [])

    def test_empty_editor_starts_with_one_group(self):
        """
        UC: Open the editor without saved filters.
        Expected Result: One AND group with a blank condition is immediately available.
        """
        # 1. Initialize without filter groups.
        self.start()
        # 2. Check the initial group and its field selector.
        expect(self.page.locator('[data-filter-group]')).to_have_count(1)
        expect(self.page.locator('[data-filter-condition]')).to_have_count(1)
        expect(self.page.get_by_label('Match conditions')).to_have_value('AND')
        expect(self.page.get_by_label('Field', exact=True)).to_have_value('')

    def test_workspace_apply_and_clear(self):
        """
        UC: Apply and clear grouped filters from the shared workspace editor.
        Expected Result: The URL and tile requests carry the same filters, preserving unrelated parameters.
        """
        self.page.evaluate("history.replaceState(null, '', '?module=hrm&page=2')")
        self.page.evaluate('window.startWorkspace()')
        self.start()
        self.add_name_condition('David')
        with self.page.expect_request('**/tile?*') as request:
            self.page.get_by_role('button', name='Apply filters', exact=True).click()
        from urllib.parse import urlparse, parse_qs
        params = parse_qs(urlparse(request.value.url).query)
        filters = [{'connector': 'AND', 'conditions': [
            {'field_path': 'tile_7:name', 'lookup_id': 'compare', 'value': 'David'},
        ]}]
        self.assertEqual(json.loads(params['filter'][0]), filters)
        url_params = parse_qs(urlparse(self.page.url).query)
        self.assertEqual(json.loads(url_params['filter'][0]), filters)
        self.assertEqual(url_params['module'], ['hrm'])
        self.assertNotIn('page', url_params)
        expect(self.page.get_by_text('Refreshed tile', exact=True)).to_be_visible()

        self.page.get_by_role('button', name='Clear', exact=True).click()
        with self.page.expect_request('**/tile?*') as request:
            self.page.get_by_role('button', name='Apply filters', exact=True).click()
        self.assertNotIn('filter', parse_qs(urlparse(request.value.url).query))
        self.assertNotIn('filter', parse_qs(urlparse(self.page.url).query))

    def test_workspace_ignores_other_filter_scopes(self):
        """
        UC: A tile's model editor or another workspace emits a filter event.
        Expected Result: The enclosing workspace leaves its URL unchanged.
        """
        self.page.evaluate('window.startWorkspace()')
        original_url = self.page.url
        for scope, scope_id in [('model', '42'), ('workspace', '99')]:
            self.page.evaluate("""detail => document.querySelector('#filters').dispatchEvent(
                new CustomEvent('bloomerp:filters-apply', {bubbles: true, detail})
            )""", {'scope': scope, 'id': scope_id, 'filters': []})
            self.assertEqual(self.page.url, original_url)
