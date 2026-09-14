"""Browser contract tests for the editor; discovery responses are fixture data."""
import json
from pathlib import Path
import subprocess
import unittest
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright, expect


class TestFilterContainerE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        static_src = Path(__file__).resolve().parents[3] / 'static_src'
        entry = '''
            import FilterContainer from './ts/components/filters/FilterContainer';
            import { PermissionsTable } from './ts/components/PermissionsTable';
            import PermissionCheckboxes from './ts/components/inputs/PermissionCheckboxes';
            import WorkspaceContainer from './ts/components/workspaces/WorkspaceContainer';
            import { registerComponent, getComponent } from './ts/components/BaseComponent';
            import { BaseWidget } from './ts/components/widgets/BaseWidget';
            class StructuredWidget extends BaseWidget {
                getValue() { return JSON.parse(this.element.querySelector('textarea').value); }
                setValue(value) { this.element.querySelector('textarea').value = JSON.stringify(value); }
            }
            registerComponent('test-structured-widget', StructuredWidget);
            registerComponent('unified-filter-container', FilterContainer);
            registerComponent('test-permission-checkboxes', PermissionCheckboxes);
            window.startPermissionTable = (entries) => {
                const editor = document.querySelector('#filters');
                editor.setAttribute('bloomerp-component', 'unified-filter-container');
                editor.dataset.maxGroups = '1';
                editor.dataset.includeControls = 'false';
                const table = document.createElement('div');
                table.dataset.contentTypeId = '1';
                table.dataset.mode = 'wizard';
                table.innerHTML = '<input id="row-policy-rules-json" type="hidden"><input id="field-policies-json" type="hidden" value="{}"><div data-row-policy-preview></div><div id="row-policy-alert"></div><div draggable="true" data-field-draggable data-field-id="1" data-field-name="name">Name field</div><div data-drop-zone="row">Drop row rule here</div><div id="permissions-modal-filter-target"></div><div id="row-policy-permissions-1" bloomerp-component="test-permission-checkboxes" data-name="row-grants"><label><input type="checkbox" name="row-grants" value="__all__">All</label><label><input type="checkbox" name="row-grants" value="view_customer">View</label></div><button id="add-row-policy-btn" type="button">Use rule</button>';
                table.querySelector('#row-policy-rules-json').value = JSON.stringify(entries);
                document.body.append(table);
                table.querySelector('#permissions-modal-filter-target').append(editor);
                const component = new PermissionsTable(table);
                component.initialize();
                window.permissionTable = component;
                window.filterComponent = getComponent(editor);
            };
            window.startWorkspace = (tileIds = ['7'], itemConfig = {}, rowColumns = 2, colspan = 1) => {
                const workspace = document.createElement('div');
                workspace.dataset.workspaceId = '42';
                workspace.dataset.layoutRenderItemUrl = '/tile';
                workspace.dataset.layout = JSON.stringify({rows: [{columns: rowColumns, items: tileIds.map(id => ({id, colspan, config: itemConfig}))}]});
                document.body.append(workspace);
                workspace.innerHTML = `<div data-layout-root><div data-layout-row data-row-columns="${rowColumns}"><div data-layout-grid>${tileIds.map(id => `<div bloomerp-component="workspace-tile" data-layout-item-id="${id}" data-colspan="${colspan}" data-max-cols="${rowColumns}" data-layout-item-config='${JSON.stringify(itemConfig)}'><div data-layout-item-body>Initial tile ${id}</div></div>`).join('')}</div></div></div>`;
                const root = document.querySelector('#filters');
                root.dataset.scope = 'workspace';
                root.dataset.scopeId = '42';
                workspace.prepend(root);
                window.workspaceColspanChangeCount = 0;
                workspace.addEventListener('layout:item-colspan-change', () => { window.workspaceColspanChangeCount += 1; });
                const component = new WorkspaceContainer(workspace);
                component.initialize();
                window.initialWorkspaceSkeletonCount = workspace.querySelectorAll('.skeleton-loader').length;
                window.workspaceComponent = component;
            };

            window.startFilters = (initial) => {
                const root = document.querySelector('#filters');
                root.dataset.initialFilters = JSON.stringify(initial);
                const component = new FilterContainer(root);
                component.initialize();
                window.filterComponent = component;
                root.addEventListener('bloomerp:filters-apply', event => { window.applied = event.detail.filters; window.appliedDetail = event.detail; });
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
        self.failed_tile_ids = set()
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.page.route('http://localhost/**', self.respond)
        self.page.goto('http://localhost/')
        self.page.add_script_tag(content=self.bundle)

    def tearDown(self):
        self.context.close()

    def respond(self, route):
        url = urlparse(route.request.url)
        params = parse_qs(url.query)
        if url.path == '/':
            route.fulfill(content_type='text/html', body='''<div id="filters" data-scope="model" data-scope-id="1"
                data-fields-url="/fields" data-lookups-url="/lookups" data-value-editor-url="/editor"></div>''')
            return
        if url.path == '/tile':
            tile_id = params['tile_id'][0]
            if tile_id in self.failed_tile_ids:
                route.fulfill(status=500, content_type='text/plain', body='Tile failed')
                return
            config = params.get('config', ['{}'])[0]
            colspan = params.get('colspan', ['1'])[0]
            max_cols = params.get('max_cols', ['4'])[0]
            route.fulfill(content_type='text/html', body=f'<div bloomerp-component="workspace-tile" data-layout-item-id="{tile_id}" data-colspan="{colspan}" data-max-cols="{max_cols}" data-layout-item-config=\'{config}\'><div data-layout-item-body>Refreshed tile {tile_id}</div></div>')
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
        self.page.get_by_role('button', name='Apply').click()
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
        self.page.get_by_role('button', name='Apply').click()
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
        self.page.get_by_role('button', name='Apply').click()
        self.assertEqual(self.page.evaluate('window.applied'), groups)

    def test_incomplete_condition_cannot_apply(self):
        """
        UC: Apply a group before selecting a field and lookup.
        Expected Result: Feedback is visible and no apply event is emitted.
        """
        # 1. Open the initial incomplete condition.
        self.start()
        # 2. Attempt to apply it.
        self.page.get_by_role('button', name='Apply').click()
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
        self.page.get_by_role('button', name='Apply').click()
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
            self.page.get_by_role('button', name='Apply', exact=True).click()
        params = parse_qs(urlparse(request.value.url).query)
        filters = [{'connector': 'AND', 'conditions': [
            {'field_path': 'tile_7:name', 'lookup_id': 'compare', 'value': 'David'},
        ]}]
        self.assertEqual(json.loads(params['filter'][0]), filters)
        url_params = parse_qs(urlparse(self.page.url).query)
        self.assertEqual(json.loads(url_params['filter'][0]), filters)
        self.assertEqual(url_params['module'], ['hrm'])
        self.assertNotIn('page', url_params)
        expect(self.page.get_by_text('Refreshed tile 7', exact=True)).to_be_visible()

        self.page.get_by_role('button', name='Clear', exact=True).click()
        with self.page.expect_request('**/tile?*') as request:
            self.page.get_by_role('button', name='Apply', exact=True).click()
        self.assertEqual(json.loads(parse_qs(urlparse(request.value.url).query)['filter'][0]), [])
        self.assertEqual(json.loads(parse_qs(urlparse(self.page.url).query)['filter'][0]), [])

    def test_workspace_loads_tiles_in_order_with_skeletons(self):
        """
        Use case: Open and then filter a workspace containing multiple tiles.
        Expected result: Every tile shows a skeleton before ordered rendering begins.
        """
        # 1. Record tile requests and initialize two tile shells.
        requested_tile_ids = []
        self.page.on(
            'request',
            lambda request: requested_tile_ids.append(parse_qs(urlparse(request.url).query)['tile_id'][0])
            if urlparse(request.url).path == '/tile' else None,
        )
        self.page.evaluate("window.startWorkspace(['7', '8'], {density: 'compact'})")

        # 2. Verify both skeletons were inserted synchronously and tiles loaded in layout order.
        self.assertEqual(self.page.evaluate('window.initialWorkspaceSkeletonCount'), 2)
        expect(self.page.get_by_text('Refreshed tile 8', exact=True)).to_be_visible()
        self.assertEqual(requested_tile_ids, ['7', '8'])
        self.assertEqual(
            self.page.locator('[data-layout-item-id="8"]').get_attribute('data-layout-item-config'),
            '{"density":"compact"}',
        )

        # 3. Apply a workspace filter and capture its immediate loading state.
        filter_skeleton_count = self.page.evaluate("""() => {
            const workspace = document.querySelector('[data-workspace-id="42"]');
            workspace.dispatchEvent(new CustomEvent('bloomerp:filters-apply', {
                bubbles: true,
                detail: {scope: 'workspace', id: '42', filters: []},
            }));
            return workspace.querySelectorAll('.skeleton-loader').length;
        }""")

        # 4. Verify filtering restored every skeleton before requesting refreshed content.
        self.assertEqual(filter_skeleton_count, 2)
        expect(self.page.get_by_text('Refreshed tile 8', exact=True)).to_be_visible()

    def test_workspace_serializes_initial_and_filter_reloads(self):
        """
        Use case: Apply a filter while the initial sequential tile load is still starting.
        Expected result: The initial sequence finishes before one latest-filter sequence replaces it.
        """
        # 1. Record every tile request and trigger a filter in the initial load's call stack.
        requested_urls = []
        self.page.on(
            'request',
            lambda request: requested_urls.append(request.url)
            if urlparse(request.url).path == '/tile' else None,
        )
        self.page.evaluate("""() => {
            window.startWorkspace(['7', '8']);
            document.querySelector('[data-workspace-id="42"]').dispatchEvent(
                new CustomEvent('bloomerp:filters-apply', {
                    bubbles: true,
                    detail: {scope: 'workspace', id: '42', filters: [{connector: 'AND', conditions: []}]},
                }),
            );
        }""")

        # 2. Wait for the queued filtered sequence to finish.
        expect(self.page.get_by_text('Refreshed tile 8', exact=True)).to_be_visible()
        self.page.wait_for_function("""() => {
            const requests = performance.getEntriesByType('resource').filter(entry => entry.name.includes('/tile?'));
            return requests.length >= 4;
        }""")

        # 3. Verify complete, non-overlapping layout-order sequences and the latest filter snapshot.
        request_params = [parse_qs(urlparse(url).query) for url in requested_urls]
        self.assertEqual([params['tile_id'][0] for params in request_params], ['7', '8', '7', '8'])
        self.assertNotIn('filter', request_params[0])
        self.assertNotIn('filter', request_params[1])
        self.assertEqual(
            json.loads(request_params[2]['filter'][0]),
            [{'connector': 'AND', 'conditions': []}],
        )
        self.assertEqual(
            json.loads(request_params[3]['filter'][0]),
            [{'connector': 'AND', 'conditions': []}],
        )

    def test_workspace_preserves_wide_colspan_during_initial_reload(self):
        """
        Use case: Open a workspace with a tile spanning more than four columns.
        Expected result: Replacement initialization preserves the saved span without emitting a change.
        """
        self.page.evaluate("window.startWorkspace(['7'], {}, 6, 6)")

        expect(self.page.get_by_text('Refreshed tile 7', exact=True)).to_be_visible()
        tile = self.page.locator('[data-layout-item-id="7"]')
        expect(tile).to_have_attribute('data-colspan', '6')
        expect(tile).to_have_attribute('data-max-cols', '6')
        self.assertEqual(self.page.evaluate('window.workspaceColspanChangeCount'), 0)

    def test_workspace_continues_after_a_tile_request_fails(self):
        """
        Use case: One tile endpoint fails while a workspace is loading in sequence.
        Expected result: That tile shows an error and later tiles still render.
        """
        self.failed_tile_ids.add('7')
        self.page.evaluate("window.startWorkspace(['7', '8'])")

        expect(self.page.get_by_text('Unable to load tile.', exact=True)).to_be_visible()
        expect(self.page.get_by_text('Refreshed tile 8', exact=True)).to_be_visible()

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

    def enable_saved_presets(self, presets=None):
        self.page.add_style_tag(path=str(Path(__file__).resolve().parents[3] / 'static/bloomerp/css/dist/styles.css'))
        self.presets = presets or []
        self.preset_requests = []
        self.save_requests = []
        self.page.evaluate("""() => {
            const root = document.querySelector('#filters');
            root.dataset.presetsUrl = '/presets';
            root.dataset.savePresetUrl = '/save-preset';
        }""")
        def get_presets(route):
            self.preset_requests.append(route.request.url)
            route.fulfill(json=self.presets)
        self.page.route('**/presets?*', get_presets)
        def save(route):
            data = route.request.post_data_json
            self.save_requests.append(data)
            record = {**data, 'id': data.get('filter_id', 'new-preset')}
            route.fulfill(json=record, status=200 if 'filter_id' in data else 201)
        self.page.route('**/save-preset', save)

    def test_save_creates_then_updates_same_identity(self):
        """
        UC: Save a new filter, edit its value, and save again.
        Expected Result: Only the first request creates; the second carries the saved ID.
        """
        self.enable_saved_presets()
        self.start()
        self.add_name_condition('David')
        self.page.get_by_label('Filter name', exact=True).fill('Named people')
        self.page.get_by_role('button', name='Save filter', exact=True).click()
        expect(self.page.get_by_role('button', name='Save filter', exact=True)).to_be_enabled()
        self.assertNotIn('filter_id', self.save_requests[0])
        self.assertEqual(self.save_requests[0]['identifier'], '1')
        self.page.get_by_label('Value', exact=True).fill('Daniel')
        self.page.get_by_role('button', name='Save filter', exact=True).click()
        expect(self.page.get_by_role('button', name='Save filter', exact=True)).to_be_enabled()
        self.assertEqual(len(self.save_requests), 2)
        self.assertEqual(self.save_requests[1]['filter_id'], 'new-preset')
        self.page.get_by_role('button', name='Apply', exact=True).click()
        self.assertEqual(self.page.evaluate('window.appliedDetail.filter_id'), 'new-preset')
        self.assertEqual(self.page.evaluate('window.applied[0].conditions[0].value'), 'Daniel')

    def test_select_loads_locally_and_edits_keep_id(self):
        """
        UC: Select a preset from the scoped list and edit its name and condition.
        Expected Result: Selection uses the fetched payload and Save updates that exact preset.
        """
        self.enable_saved_presets([{'id': 'existing', 'name': 'Existing', 'scope': 'model', 'identifier': '1',
                                   'filters': [{'connector': 'OR', 'conditions': [{'field_path': 'name', 'lookup_id': 'compare', 'value': 'David'}]}]}])
        self.page.evaluate("""() => {
            const root = document.querySelector('#filters');
            root.setAttribute('bloomerp-component', 'unified-filter-container');
            const parent = document.createElement('div');
            parent.id = 'parent-dropdown';
            parent.style.cssText = 'width:600px; margin:40px; overflow:hidden';
            root.before(parent);
            parent.append(root);
            document.addEventListener('click', event => {
                if (!parent.contains(event.target)) parent.style.display = 'none';
            });
        }""")
        self.start()
        chooser = self.page.get_by_role('menu', name='Saved filters', exact=True)
        expect(chooser).to_be_hidden()
        expect(self.page.locator('select[aria-label="Saved filters"]')).to_have_count(0)
        self.assertEqual(self.preset_requests, [])
        select_button = self.page.get_by_role('button', name='Select', exact=True)
        expect(select_button).to_be_visible()
        self.assertIn('btn-primary', select_button.get_attribute('class'))
        parent = self.page.locator('#parent-dropdown')
        parent_box = parent.bounding_box()
        filter_box = self.page.locator('#filters').bounding_box()
        select_button.click()
        expect(chooser).to_be_visible()
        expect(chooser.get_by_role('menuitem')).to_have_count(2)
        self.assertEqual(chooser.evaluate("""menu => Array.from(menu.children).map(row =>
            row.querySelector('input') ? 'search' : row.getAttribute('role') || 'results')"""),
            ['search', 'menuitem', 'separator', 'results'])
        expect(chooser.get_by_role('menuitem').first).to_have_text('Add filter')
        expect(chooser.get_by_role('separator')).to_have_count(1)
        expect(chooser.get_by_text('New filter', exact=True)).to_have_count(0)
        self.assertTrue(chooser.evaluate('(menu) => menu.parentElement === document.body'))
        self.assertEqual(parent.bounding_box(), parent_box)
        self.assertEqual(self.page.locator('#filters').bounding_box(), filter_box)
        anchor = select_button.bounding_box()
        menu = chooser.bounding_box()
        self.assertAlmostEqual(menu['y'], anchor['y'] + anchor['height'] + 8, delta=1)
        self.assertAlmostEqual(menu['x'] + menu['width'], anchor['x'] + anchor['width'], delta=1)
        chooser.get_by_role('menuitem', name='Existing', exact=True).click()
        expect(chooser).to_be_hidden()
        expect(parent).to_be_visible()
        expect(self.page.get_by_label('Filter name', exact=True)).to_have_value('Existing')
        expect(self.page.get_by_label('Value', exact=True)).to_have_value('David')
        expect(self.page.get_by_label('Match conditions', exact=True)).to_have_value('OR')
        self.assertEqual(len(self.preset_requests), 1)
        self.page.get_by_label('Filter name', exact=True).fill('Renamed')
        self.page.get_by_label('Value', exact=True).fill('Emma')
        self.page.get_by_role('button', name='Save filter', exact=True).click()
        expect(self.page.get_by_role('button', name='Save filter', exact=True)).to_be_enabled()
        self.assertEqual(self.save_requests[0]['filter_id'], 'existing')
        self.assertEqual(self.save_requests[0]['name'], 'Renamed')
        self.page.get_by_role('button', name='Apply', exact=True).click()
        self.assertEqual(self.page.evaluate('window.appliedDetail.filter_id'), 'existing')

    def test_saved_menu_empty_error_and_dismissal(self):
        """
        UC: Open an empty saved-filter menu, dismiss it, and encounter a loading failure.
        Expected Result: Menu states stay anchored; outside click and Escape close it.
        """
        self.enable_saved_presets()
        self.start()
        trigger = self.page.get_by_role('button', name='Select', exact=True)
        menu = self.page.get_by_role('menu', name='Saved filters', exact=True)
        trigger.click()
        expect(menu.get_by_text('No saved filters yet.', exact=True)).to_be_visible()
        expect(menu.get_by_role('menuitem')).to_have_count(1)
        expect(menu.get_by_role('menuitem', name='Add filter', exact=True)).to_be_visible()
        expect(menu.get_by_role('separator')).to_have_count(1)
        expect(menu.get_by_text('New filter', exact=True)).to_have_count(0)
        self.page.keyboard.press('Escape')
        expect(menu).to_be_hidden()
        expect(trigger).to_be_focused()
        trigger.click()
        expect(menu.get_by_text('No saved filters yet.', exact=True)).to_be_visible()
        self.page.get_by_label('Filter name', exact=True).click()
        expect(menu).to_be_hidden()
        self.page.route('**/presets?*', lambda route: route.fulfill(status=500, json={'error': 'Could not load presets'}))
        trigger.click()
        expect(menu.get_by_role('alert')).to_have_text('Could not load presets')

    def test_saved_menu_loading_state(self):
        """
        UC: Open Select while the scoped list request is pending.
        Expected Result: The menu shows loading until its items arrive.
        """
        self.enable_saved_presets()
        pending = []
        self.page.route('**/presets?*', lambda route: pending.append(route))
        self.start()
        self.page.get_by_role('button', name='Select', exact=True).click()
        menu = self.page.get_by_role('menu', name='Saved filters', exact=True)
        expect(menu.get_by_role('status')).to_have_text('Loading saved filters…')
        self.assertEqual(len(pending), 1)
        pending[0].fulfill(json=[])
        expect(menu.get_by_text('No saved filters yet.', exact=True)).to_be_visible()

    def test_saved_search_and_add_reset(self):
        """
        UC: Search saved names, load one, then use Add filter to create a fresh filter.
        Expected Result: Search is case insensitive; Add stays visible and clears saved identity/name/groups.
        """
        groups = [{'connector': 'OR', 'conditions': [{'field_path': 'name', 'lookup_id': 'compare', 'value': 'David'}]}]
        self.enable_saved_presets([
            {'id': 'people', 'name': 'People', 'scope': 'model', 'identifier': '1', 'filters': groups},
            {'id': 'teams', 'name': 'Teams', 'scope': 'model', 'identifier': '1', 'filters': groups},
        ])
        self.start()
        trigger = self.page.get_by_role('button', name='Select', exact=True)
        trigger.click()
        menu = self.page.get_by_role('menu', name='Saved filters', exact=True)
        search = menu.get_by_role('searchbox', name='Search saved filters')
        expect(search).to_be_focused()
        search.fill('pEoP')
        expect(menu.get_by_role('menuitem')).to_have_text(['Add filter', 'People'])
        search.fill('missing')
        expect(menu.get_by_role('menuitem')).to_have_text(['Add filter'])
        expect(menu.get_by_text('No matching filters.', exact=True)).to_be_visible()
        self.assertEqual(menu.get_by_role('status').evaluate("node => node.parentElement.previousElementSibling.getAttribute('role')"), 'separator')
        search.fill('')
        expect(menu.get_by_role('menuitem')).to_have_text(['Add filter', 'People', 'Teams'])
        self.assertEqual(len(self.preset_requests), 1)
        menu.get_by_role('menuitem', name='People', exact=True).click()
        expect(self.page.get_by_label('Filter name', exact=True)).to_have_value('People')
        trigger.click()
        expect(search).to_be_focused()
        search.fill('nothing')
        self.page.keyboard.press('Tab')
        expect(menu.get_by_role('menuitem', name='Add filter', exact=True)).to_be_focused()
        self.page.keyboard.press('Enter')
        expect(menu).to_be_hidden()
        name = self.page.get_by_label('Filter name', exact=True)
        expect(name).to_have_value('')
        expect(name).to_be_focused()
        expect(self.page.locator('[data-filter-group]')).to_have_count(1)
        expect(self.page.get_by_label('Match conditions', exact=True)).to_have_value('AND')
        self.add_name_condition('Emma')
        name.fill('Fresh')
        self.page.get_by_role('button', name='Save filter', exact=True).click()
        expect(self.page.get_by_role('button', name='Save filter', exact=True)).to_be_enabled()
        self.assertNotIn('filter_id', self.save_requests[0])
        self.assertEqual(self.save_requests[0]['name'], 'Fresh')

    def test_saved_overlay_repositions_and_cleans_up(self):
        """
        UC: Resize and scroll with the saved-filter overlay open, then destroy the editor.
        Expected Result: The panel follows Select and is removed on destruction.
        """
        self.enable_saved_presets()
        self.page.locator('#filters').evaluate("root => root.style.cssText = 'width:600px; margin:200px 40px'")
        self.page.evaluate("document.body.style.minHeight = '2000px'")
        self.start()
        trigger = self.page.get_by_role('button', name='Select', exact=True)
        trigger.click()
        menu = self.page.get_by_role('menu', name='Saved filters', exact=True)
        expect(menu.get_by_text('No saved filters yet.', exact=True)).to_be_visible()
        self.page.set_viewport_size({'width': 1000, 'height': 800})
        self.page.evaluate('window.scrollTo(0, 100)')
        self.page.wait_for_function("""() => {
            const menu = document.querySelector('[role=menu][aria-label="Saved filters"]');
            const trigger = document.querySelector('button[aria-haspopup=menu]');
            return Math.abs(menu.getBoundingClientRect().top - trigger.getBoundingClientRect().bottom - 8) < 1;
        }""")
        self.page.evaluate('window.filterComponent.destroy()')
        expect(menu).to_have_count(0)

    def test_permission_table_conditions_and_separate_entries(self):
        """
        UC: Add conditions to one rule, edit its connector, then add another table entry.
        Expected Result: Each entry keeps one group; Add condition does not create a separate grant.
        """
        self.page.evaluate('window.startPermissionTable([])')
        self.page.locator('[data-field-draggable]').drag_to(self.page.locator('[data-drop-zone]'))
        self.page.get_by_label('Lookup', exact=True).select_option('compare')
        self.page.get_by_label('Value', exact=True).fill('David')
        self.page.get_by_role('button', name='Add condition', exact=True).click()
        self.add_name_condition('Emma')
        self.page.get_by_label('View', exact=True).check()
        self.page.get_by_role('button', name='Use rule', exact=True).click()
        entry = json.loads(self.page.locator('#row-policy-rules-json').input_value())[0]
        self.assertEqual(entry, {'permissions': ['view_customer'], 'rule': {'connector': 'AND', 'conditions': [
            {'field_path': 'name', 'lookup_id': 'compare', 'value': 'David'},
            {'field_path': 'name', 'lookup_id': 'compare', 'value': 'Emma'},
        ]}})
        self.page.locator('[data-row-policy-index="0"] > span').click()
        self.page.get_by_label('Match conditions', exact=True).select_option('OR')
        expect(self.page.get_by_label('Value', exact=True)).to_have_count(2)
        self.page.get_by_label('Value', exact=True).first.fill('Daniel')
        self.page.get_by_role('button', name='Use rule', exact=True).click()
        updated = json.loads(self.page.locator('#row-policy-rules-json').input_value())
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]['rule']['connector'], 'OR')
        self.assertEqual(updated[0]['rule']['conditions'][0]['value'], 'Daniel')
        self.page.locator('[data-field-draggable]').drag_to(self.page.locator('[data-drop-zone]'))
        self.page.get_by_label('Lookup', exact=True).select_option('compare')
        self.page.get_by_label('Value', exact=True).fill('Tessa')
        self.page.get_by_label('View', exact=True).check()
        self.page.get_by_role('button', name='Use rule', exact=True).click()
        entries = json.loads(self.page.locator('#row-policy-rules-json').input_value())
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0], updated[0])
        self.assertEqual(entries[1]['rule']['connector'], 'AND')
        self.assertEqual(entries[1]['rule']['conditions'][0]['value'], 'Tessa')
        self.page.locator('[data-row-policy-index="0"] > span').click()
        expect(self.page.get_by_label('Match conditions', exact=True)).to_have_value('OR')
        expect(self.page.get_by_label('Value', exact=True).first).to_have_value('Daniel')

    def test_filter_widget_readonly_and_disabled(self):
        """
        UC: Render a disabled or readonly FilterWidget.
        Expected Result: The editor is inert; disabled values are excluded from form submission.
        """
        for attribute in ('readonly', 'disabled'):
            with self.subTest(attribute=attribute):
                self.page.locator('#filters').evaluate('(root, attr) => root.setAttribute(attr, "")', attribute)
                self.start()
                self.assertTrue(self.page.locator('#filters').evaluate('root => root.inert'))
                self.assertEqual(self.page.locator('#filters input[type=hidden]').is_disabled(), attribute == 'disabled')
                self.page.evaluate('window.filterComponent.destroy()')
                self.page.locator('#filters').evaluate('(root, attr) => root.removeAttribute(attr)', attribute)

    def test_permission_table_nested_restore_and_invalid_draft(self):
        """
        UC: Restore nested OR conditions, then attempt an incomplete edit.
        Expected Result: Complete field paths survive; an invalid draft cannot replace the rule.
        """
        entry = {'permissions': ['view_customer'], 'rule': {'connector': 'OR', 'conditions': [{'field_path': 'relation__name', 'lookup_id': 'compare', 'value': 'David'}]}}
        self.page.evaluate('entries => window.startPermissionTable(entries)', [entry])
        self.page.locator('[data-row-policy-index="0"] > span').click()
        expect(self.page.get_by_label('Value', exact=True)).to_have_value('David')
        expect(self.page.get_by_label('Match conditions', exact=True)).to_have_value('OR')
        self.page.get_by_role('button', name='Add condition', exact=True).click()
        self.page.get_by_role('button', name='Use rule', exact=True).click()
        self.assertEqual(json.loads(self.page.locator('#row-policy-rules-json').input_value()), [entry])
        expect(self.page.locator('#row-policy-alert')).to_contain_text('Complete every filter condition')

    def test_permission_table_no_controls_live_value(self):
        """
        UC: Edit a permission entry with outer controls disabled.
        Expected Result: Only condition controls remain; hidden JSON updates before Use rule.
        """
        self.enable_saved_presets()
        self.page.evaluate('window.startPermissionTable([])')
        for label in ('Apply', 'Clear', 'Select', 'Save filter', 'Add group'):
            expect(self.page.get_by_role('button', name=label, exact=True)).to_have_count(0)
        expect(self.page.get_by_label('Filter name', exact=True)).to_have_count(0)
        expect(self.page.locator('[data-filter-controls]')).to_have_count(0)
        expect(self.page.get_by_role('menu', name='Saved filters')).to_have_count(0)
        self.assertEqual(self.preset_requests, [])
        self.page.get_by_role('button', name='Add condition', exact=True).click()
        self.add_name_condition('David')
        group = {'connector': 'AND', 'conditions': [{'field_path': 'name', 'lookup_id': 'compare', 'value': 'David'}]}
        self.assertEqual(json.loads(self.page.locator('#filters input[type=hidden]').input_value()), [group])
        self.assertEqual(self.page.locator('#row-policy-rules-json').input_value(), '[]')
        self.page.get_by_label('Match conditions', exact=True).select_option('OR')
        group['connector'] = 'OR'
        self.assertEqual(json.loads(self.page.locator('#filters input[type=hidden]').input_value()), [group])
        self.page.get_by_label('View', exact=True).check()
        self.page.get_by_role('button', name='Use rule', exact=True).click()
        self.assertEqual(json.loads(self.page.locator('#row-policy-rules-json').input_value())[0]['rule'], group)

    def test_no_controls_form_submission_and_invalid_draft(self):
        """
        UC: Submit a no-controls editor inside a form without applying filters.
        Expected Result: Live JSON submits without an apply event; incomplete edits cannot submit stale JSON.
        """
        self.page.evaluate("""() => {
            const root = document.querySelector('#filters');
            root.dataset.includeControls = 'false';
            const form = document.createElement('form');
            root.before(form);
            form.append(root);
            window.appliedCount = 0;
            root.addEventListener('bloomerp:filters-apply', () => window.appliedCount++);
            form.addEventListener('submit', event => {
                if (!event.defaultPrevented) window.submitted = new FormData(form).get('filter');
                event.preventDefault();
            });
        }""")
        self.start()
        expect(self.page.get_by_role('button', name='Add group', exact=True)).to_be_visible()
        self.add_name_condition('Emma')
        self.page.evaluate("document.querySelector('form').dispatchEvent(new Event('submit', {bubbles:true, cancelable:true}))")
        submitted = self.page.evaluate('window.submitted')
        self.assertEqual(json.loads(submitted)[0]['conditions'][0]['value'], 'Emma')
        self.assertEqual(self.page.evaluate('window.appliedCount'), 0)
        self.page.get_by_role('button', name='Add condition', exact=True).click()
        expect(self.page.locator('#filters input[type=hidden]')).to_have_value('')
        self.page.evaluate("document.querySelector('form').dispatchEvent(new Event('submit', {bubbles:true, cancelable:true}))")
        self.assertEqual(self.page.evaluate('window.submitted'), submitted)
        expect(self.page.get_by_text('Complete every filter condition before applying.', exact=True)).to_be_visible()
        self.page.get_by_role('button', name='Remove condition', exact=True).last.click()
        self.assertEqual(json.loads(self.page.locator('#filters input[type=hidden]').input_value())[0]['conditions'][0]['value'], 'Emma')
