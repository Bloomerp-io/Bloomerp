"""Shared filter journeys with host-owned fixtures and result assertions."""

from typing import Literal

from playwright.sync_api import Locator, expect

from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.models.filters.filter import SavedFilter
from bloomerp.tests.base import E2EAction, E2ERequestScenario
from bloomerp.tests.base.e2e_test_case import E2EValidator


class FilterE2EMixin:
    """Contract for BloomerpE2ETestCase subclasses.

    Supply scope ('model' or 'workspace') and implement the five hooks below.
    prepare_filter_host resets fixtures/preferences before EVERY scenario.
    Fixtures must distinguish first_name=David, Kyle and unfiltered results.
    The base test supplies page, admin_user and browser authentication.
    The mixin owns UI actions and SavedFilter assertions; the host owns data.
    Locators are resolved when actions execute, so HTMX replacements are safe.
    Override filter_field_path for the host's first-name field identifier
    (for example shared:first_name on a workspace).
    """

    scope: Literal['model', 'workspace']
    filter_field_path = 'first_name'

    def prepare_filter_host(self) -> None:
        raise NotImplementedError

    def filter_page_url(self) -> str:
        raise NotImplementedError

    def filter_scope_id(self) -> str:
        raise NotImplementedError

    def filter_host(self) -> Locator:
        raise NotImplementedError

    def assert_filter_results(self, first_name: str | None) -> None:
        """Assert exact host results; None means all fixture records."""
        raise NotImplementedError

    def _prepare_filters(self) -> None:
        self.prepare_filter_host()
        self._saved_filter_id = None
        SavedFilter.objects.filter(scope=self.scope, identifier=self.filter_scope_id()).delete()

    def _editor(self) -> Locator:
        modal = self.page.locator('[id^="rendered-filter-"][bloomerp-component="modal"]:visible')
        if modal.count():
            return modal.locator('[bloomerp-component="unified-filter-container"]')
        return self.filter_host().locator('[data-filter-host-editor] [bloomerp-component="unified-filter-container"]:visible')

    def _condition(self, group: int = 0, condition: int = 0) -> Locator:
        return self._editor().locator('[data-filter-group]').nth(group).locator('.filter-condition').nth(condition)

    def _level(self, group: int = 0, condition: int = 0, level: int = 0) -> Locator:
        return self._condition(group, condition).locator('.filter-path-level').nth(level)

    def _labels(self) -> Locator:
        return self.filter_host().locator(
            f'[data-rendered-filters][data-scope="{self.scope}"][data-scope-id="{self.filter_scope_id()}"] '
            '[data-rendered-filter-list] [bloomerp-component="rendered-filter"]'
        )

    def click_filter_button(self) -> E2EAction:
        return E2EAction(lambda: self.filter_host().get_by_role('button', name='Filter', exact=True).click(), name='Open filter editor')

    def set_filter_field(self, field: str, level: int = 0, *, group: int = 0, condition: int = 0) -> E2EAction:
        """Select by displayed label; field option values are internal indexes."""
        return E2EAction(lambda: self._level(group, condition, level).get_by_label('Field', exact=True).select_option(label=field), name=f'Select field {field}')

    def set_filter_lookup(self, lookup_id: str, level: int = 0, *, group: int = 0, condition: int = 0) -> E2EAction:
        return E2EAction(lambda: self._level(group, condition, level).get_by_label('Lookup', exact=True).select_option(lookup_id), name=f'Select lookup {lookup_id}')

    def set_filter_value(self, value: str, *, group: int = 0, condition: int = 0) -> E2EAction:
        # These journeys use a CharField. Complex widgets have their own tests.
        return E2EAction(lambda: self._condition(group, condition).locator('.filter-value-editor input:not([type="hidden"])').fill(str(value)), name=f'Enter value {value}')

    def apply_filters(self, validators: E2EValidator | list[E2EValidator] | None = None) -> E2EAction:
        return E2EAction(lambda: self._editor().get_by_role('button', name='Apply', exact=True).click(), validators=validators, name='Apply filters')

    def set_filter_name(self, name: str) -> E2EAction:
        return E2EAction(lambda: self._editor().get_by_role('textbox', name='Filter name', exact=True).fill(name), name=f'Name filter {name}')

    def save_filter(self, *, updating: bool = False, value: str = 'David') -> E2EAction:
        def execute():
            old_id = self._saved_filter_id
            with self.page.expect_response(lambda r: '/components/filters/save' in r.url and r.request.method == 'POST') as pending:
                self._editor().get_by_role('button', name='Save filter', exact=True).click()
            response = pending.value
            self.assertEqual(response.status, 200 if updating else 201, response.text())
            record = SavedFilter.objects.get(pk=response.json()['id'])
            self.assertEqual(record.scope, self.scope)
            self.assertEqual(record.identifier, self.filter_scope_id())
            self.assertEqual(record.name, 'Named people')
            self.assertEqual(record.filters, self._filter_definition(value))
            if updating:
                self.assertEqual(str(record.pk), old_id)
            self._saved_filter_id = str(record.pk)
            self.assertEqual(SavedFilter.objects.filter(scope=self.scope, identifier=self.filter_scope_id()).count(), 1)
        return E2EAction(execute, name='Update saved instance' if updating else 'Save new filter')

    def click_applied_filter_by_position(self, position: int) -> E2EAction:
        def execute():
            self._close_filter_dropdown()
            self._labels().nth(position).get_by_role('button').click()
        return E2EAction(execute, name=f'Open applied filter {position}')

    def _close_filter_dropdown(self) -> None:
        editor = self.filter_host().locator('[data-filter-host-editor] [bloomerp-component="unified-filter-container"]:visible')
        if editor.count():
            self.filter_host().get_by_role('button', name='Filter', exact=True).click()
            expect(editor).to_have_count(0)

    def click_applied_filter_by_id(self, filter_id: str) -> E2EAction:
        def execute():
            self._close_filter_dropdown()
            self.filter_host().locator(f'[data-saved-filter-id="{filter_id}"] button').click()
        return E2EAction(execute, name=f'Open saved filter {filter_id}')

    def edit_applied_filter_by_position(self, position: int) -> E2EAction:
        def execute():
            self.click_applied_filter_by_position(position).execute()
            self.page.get_by_role('menuitem', name='Edit', exact=True).click()
            expect(self._editor()).to_be_visible()
        return E2EAction(execute, name=f'Edit applied filter {position}')

    def _remove_applied_filter(self):
        def execute():
            self.click_applied_filter_by_position(0).execute()
            self.page.get_by_role('menuitem', name='Remove', exact=True).click()
            expect(self._labels()).to_have_count(0)
            self.assert_filter_results(None)
        return E2EAction(execute, name='Remove filter and restore all results')

    def _assert_saved_editor(self):
        expect(self._editor().get_by_role('textbox', name='Filter name', exact=True)).to_have_value('Named people')
        expect(self._level().get_by_label('Field', exact=True).locator('option:checked')).to_have_text('First Name')
        expect(self._level().get_by_label('Lookup', exact=True)).to_have_value('equals')
        expect(self._condition().locator('.filter-value-editor input:not([type="hidden"])')).to_have_value('David')

    def _assert_saved_label(self):
        expect(self._labels()).to_have_count(1)
        expect(self._labels().first).to_have_attribute('data-saved-filter-id', self._saved_filter_id)
        expect(self._labels().first).to_have_text('Named people')
        self.assert_filter_results('David')

    def _fresh_filter(self):
        return [self.click_filter_button(), self.set_filter_field('First Name'), self.set_filter_lookup('equals'),
                self.set_filter_value('David'), self.apply_filters(lambda: self.assert_filter_results('David'))]

    def _filter_definition(self, value):
        return [Filter(connector='AND', conditions=[FilterCondition(field_path=self.filter_field_path, lookup_id='equals', value=value)]).model_dump(mode='json')]

    def _prepare_saved_filter(self):
        self._prepare_filters()
        record = SavedFilter.objects.create(name='Named people', scope=self.scope,
                                            identifier=self.filter_scope_id(), filters=self._filter_definition('David'))
        self._saved_filter_id = str(record.pk)

    def _select_saved_filter(self):
        def execute():
            self._editor().get_by_role('button', name='Select', exact=True).click()
            self.page.get_by_role('menuitem', name='Named people', exact=True).click()
            self._assert_saved_editor()
        return E2EAction(execute, name='Select existing saved filter')

    def get_filter_test_scenarios(self) -> list[E2ERequestScenario]:
        def scenario(name, description, actions, prepare=None):
            return E2ERequestScenario(
                name=name,
                description=description,
                actions=actions,
                user=self.admin_user,
                url=self.filter_page_url,
                prepare=prepare or self._prepare_filters,
            )

        return [
            scenario(
                'Apply a fresh filter, edit it and save it',
                """
                UC: Save a freshly applied filter through its edit modal.

                Expected Result: Applying after Save shows its name and ID;
                reopening restores the saved instance. Saving an edit updates
                it without duplication.
                """,
                [
                    *self._fresh_filter(),
                    self.edit_applied_filter_by_position(0),
                    self.set_filter_name('Named people'),
                    self.save_filter(),
                    self.apply_filters(self._assert_saved_label),
                    self.edit_applied_filter_by_position(0),
                    E2EAction(self._assert_saved_editor, name='Check restored editor'),
                    self.set_filter_value('Kyle'),
                    self.save_filter(updating=True, value='Kyle'),
                    self.apply_filters(lambda: self.assert_filter_results('Kyle')),
                ],
            ),
            scenario(
                'Select a saved filter, apply it and edit the same instance',
                """
                UC: Apply an existing preset and reopen its rendered label.

                Expected Result: Its name, conditions and identity survive.
                Save updates that record and Apply replaces the active results.
                """,
                [
                    self.click_filter_button(),
                    self._select_saved_filter(),
                    self.apply_filters(self._assert_saved_label),
                    self.edit_applied_filter_by_position(0),
                    E2EAction(self._assert_saved_editor, name='Check selected instance'),
                    self.set_filter_value('Kyle'),
                    self.save_filter(updating=True, value='Kyle'),
                    self.apply_filters(lambda: self.assert_filter_results('Kyle')),
                ],
                prepare=self._prepare_saved_filter,
            ),
            scenario(
                'Removing a normal filter',
                """
                UC: Remove an applied unsaved filter.

                Expected Result: Its label disappears and unfiltered records return.
                """,
                [*self._fresh_filter(), self._remove_applied_filter()],
            ),
            scenario(
                'Applying a saved filter',
                """
                UC: User can select a saved filter, make changes, and apply it afterwards

                Expected Result: The saved filter should not persist the applied changes
                """,
                [
                    self.click_filter_button(), self._select_saved_filter(),
                    self.set_filter_value('Kyle'),
                    self.apply_filters(lambda: self.assert_filter_results('Kyle')),
                    E2EAction(lambda: self.assertEqual(
                        SavedFilter.objects.get(pk=self._saved_filter_id).filters,
                        self._filter_definition('David'),
                    ), name='Check that Apply did not save changes'),
                ],
                prepare=self._prepare_saved_filter,
            )
        ]

    def filter_default_host(self):
        """Return the persisted effective workspace/list preference."""
        raise NotImplementedError

    def share_filter_host(self):
        """Make the prepared host shared with admin_user, owned by another user."""
        raise NotImplementedError

    def _prepare_defaults(self):
        self._prepare_saved_filter()
        self.filter_default_host().add_default_filter(SavedFilter.objects.get(pk=self._saved_filter_id))

    def _prepare_shared_defaults(self):
        self._prepare_defaults()
        self.share_filter_host()

    def _default_scenario(self, name, description, actions, prepare=None):
        self._run_request_scenario(E2ERequestScenario(
            name=name, description=description, actions=actions,
            user=self.admin_user, url=self.filter_page_url,
            prepare=prepare or self._prepare_defaults,
        ), name)

    def _set_default(self):
        def execute():
            self.click_applied_filter_by_position(0).execute()
            with self.page.expect_response(lambda r: '/components/filters/defaults' in r.url and r.request.method == 'POST') as pending:
                self.page.get_by_role('menuitem', name='Set default', exact=True).click()
            self.assertEqual(pending.value.status, 200, pending.value.text())
            record = SavedFilter.objects.get(pk=pending.value.json()['id'])
            self.assertEqual(record.name, 'Filter 1')
            self.assertEqual(record.filters, self._filter_definition('David'))
            self.assertTrue(self.filter_default_host().default_filters.filter(pk=record.pk).exists())
            expect(self._labels().first).to_have_text(record.name)
            expect(self._labels().first).to_have_attribute('data-default-filter-id', str(record.pk))
        return E2EAction(execute, name='Save and attach a fresh default')

    def test_set_fresh_filter_as_default(self):
        """UC: Set a fresh filter as default.
        Expected Result: Save as Filter n, associate with the host and restore on a clean URL.
        """
        self._default_scenario('Set a fresh default', self.test_set_fresh_filter_as_default.__doc__, [
            *self._fresh_filter(), self._set_default(),
            E2EAction(lambda: self.goto(self.filter_page_url()), name='Open a clean URL'),
            E2EAction(lambda: self.assert_filter_results('David'), name='Check persisted filtering'),
        ], prepare=self._prepare_filters)

    def test_remove_default_filter(self):
        """UC: Remove a default filter.
        Expected Result: Remove its association and label, retain its saved record, and restore all results.
        """
        def check_removed():
            self.assertFalse(self.filter_default_host().default_filters.exists())
            self.assertTrue(SavedFilter.objects.filter(pk=self._saved_filter_id).exists())
            self.goto(self.filter_page_url())
            self.assert_filter_results(None)
            expect(self._labels()).to_have_count(0)
        self._default_scenario('Remove a default', self.test_remove_default_filter.__doc__, [
            E2EAction(self._assert_saved_label, name='Check loaded default'),
            self._remove_applied_filter(), E2EAction(check_removed, name='Check persisted removal'),
        ])

    def test_load_default_filters(self):
        """UC: Open a host with saved defaults.
        Expected Result: Restore named default labels and filtered results.
        """
        self._default_scenario('Load defaults', self.test_load_default_filters.__doc__, [
            E2EAction(self._assert_saved_label, name='Check default identity and results'),
            self.click_filter_button(),
            self.apply_filters(self._assert_saved_label),
            E2EAction(lambda: expect(self._labels().first).to_have_attribute(
                'data-default-filter-id', self._saved_filter_id,
            ), name='Reapplying retains the default identity'),
        ])

    def test_load_shared_default_filters(self):
        """UC: Open another user's shared preference.
        Expected Result: Apply its defaults without offering owner-only default changes.
        """
        def check_read_only_defaults():
            self.click_applied_filter_by_position(0).execute()
            expect(self.page.get_by_role('menuitem', name='Remove', exact=True)).to_have_count(0)
            expect(self.page.get_by_role('menuitem', name='Set default', exact=True)).to_have_count(0)
            from django.urls import reverse
            self.client.force_login(self.admin_user)
            response = self.client.post(reverse('components_filters_defaults'), data={
                'scope': self.scope, 'host_id': str(self.filter_default_host().pk),
                'action': 'remove', 'filter_id': self._saved_filter_id,
            }, content_type='application/json')
            self.assertEqual(response.status_code, 403)
            self.assertTrue(self.filter_default_host().default_filters.filter(pk=self._saved_filter_id).exists())
            response = self.client.post(reverse('components_filters_save'), data={
                'scope': self.scope, 'identifier': self.filter_scope_id(),
                'filter_id': self._saved_filter_id, 'name': 'Changed by recipient',
                'filters': self._filter_definition('Kyle'),
            }, content_type='application/json')
            self.assertEqual(response.status_code, 403)
            self.assertEqual(SavedFilter.objects.get(pk=self._saved_filter_id).filters, self._filter_definition('David'))
            self.page.keyboard.press('Escape')
        self._default_scenario('Load shared defaults', self.test_load_shared_default_filters.__doc__, [
            E2EAction(self._assert_saved_label, name='Check shared defaults'),
            E2EAction(check_read_only_defaults, name='Verify owner-only changes'),
            self.edit_applied_filter_by_position(0),
            self.set_filter_value('Kyle'),
            self.apply_filters(lambda: self.assert_filter_results('Kyle')),
        ], prepare=self._prepare_shared_defaults)
