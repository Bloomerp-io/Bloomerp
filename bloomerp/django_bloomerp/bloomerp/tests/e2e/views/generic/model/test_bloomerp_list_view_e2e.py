from unittest import skip
from types import ModuleType

from django.contrib.contenttypes.models import ContentType
from django.test import override_settings
from django.urls import get_resolver, path, reverse
from playwright.sync_api import Locator, expect

from bloomerp.models.application_field import ApplicationField
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.tests.base import E2EAction, E2ERequestScenario, e2e_test_case
from bloomerp.tests.e2e.mixins.filters_e2e_mixin import FilterE2EMixin
from bloomerp.utils.models import get_list_view_url
from bloomerp.views.generic.model.list import BloomerpListView


class TestBloomerpListViewE2E(FilterE2EMixin, e2e_test_case.BloomerpE2ETestCase):
    """Real list-view integration of the shared filter journeys."""

    scope = 'model'
    auto_create_customers = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Customer can share a route name with an installed customer module.
        # Bind this suite's list route to its dynamic model, not that module.
        urlconf = ModuleType('filter_list_e2e_urls')
        urlconf.urlpatterns = [
            *get_resolver().url_patterns,
            path('e2e/filter-customers/', BloomerpListView.as_view(model=cls.CustomerModel),
                 name=get_list_view_url(cls.CustomerModel)),
        ]
        settings_override = override_settings(ROOT_URLCONF=urlconf)
        settings_override.enable()
        cls.addClassCleanup(settings_override.disable)

    def prepare_filter_host(self) -> None:
        self.CustomerModel.objects.all().delete()
        self.customers = [
            self.create_customer('David', 'One', 21),
            self.create_customer('David', 'Two', 35),
            self.create_customer('Kyle', 'Three', 27),
            self.create_customer('Alex', 'Four', 42),
        ]
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        UserListViewPreference.objects.filter(content_type=content_type).delete()
        fields = ApplicationField.objects.filter(content_type=content_type, field__in=['first_name', 'last_name'])
        self.preference = UserListViewPreference.objects.create(
            user=self.admin_user, content_type=content_type, selected=True,
            view_type='table', display_fields={'table': list(fields.values_list('pk', flat=True))},
        )

    def filter_default_host(self):
        return self.preference

    def share_filter_host(self):
        self.preference.user = self.normal_user
        self.preference.save()
        self.preference.shared_with_users.add(self.admin_user)
        UserListViewPreference.objects.create(
            user=self.admin_user, content_type=self.preference.content_type,
            source_object=self.preference, selected=True,
        )

    def filter_page_url(self) -> str:
        return reverse(get_list_view_url(self.CustomerModel))

    def filter_scope_id(self) -> str:
        return str(ContentType.objects.get_for_model(self.CustomerModel).pk)

    def filter_host(self) -> Locator:
        return self.page.locator(f'[bloomerp-component="dataview-container"][data-content-type-id="{self.filter_scope_id()}"]')

    def assert_filter_results(self, first_name: str | None) -> None:
        expected = [customer for customer in self.customers if first_name is None or customer.first_name == first_name]
        rows = self.filter_host().locator('tbody tr').filter(has=self.page.locator('[bloomerp-component="datatable-cell"]'))
        expect(rows).to_have_count(len(expected))
        for customer in expected:
            expect(rows.filter(has=self.page.locator(f'[data-object-id="{customer.pk}"]'))).to_have_count(1)

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        return self.get_filter_test_scenarios()

    def test_create_refreshes_only_data_view(self) -> None:
        """Exercise modal completion and reopening while retaining the current search."""
        scenario = E2ERequestScenario(
            name="Create from a filtered list without reloading the page",
            user=self.admin_user,
            prepare=self.prepare_filter_host,
            url=self.filter_page_url,
            actions=[E2EAction(
                name="Create a customer and reopen the clean modal",
                execute=self.create_from_list_modal,
            )],
        )
        self._run_request_scenario(scenario, scenario.name)

    def create_from_list_modal(self) -> None:
        """Verify immediate save feedback, list replacement, focus, and a fresh form."""
        self.filter_host().locator('input[id^="data-view-search-input-"]').fill('David')
        self.assert_filter_results('David')
        original_url = self.page.url
        self.page.locator('body').evaluate(
            "element => element.setAttribute('data-create-test-marker', 'survived')"
        )
        self.filter_host().locator('[data-dataview-create-button]').click()
        modal = self.page.locator('#create-object-modal')
        expect(modal).to_be_visible()
        form = modal.locator('form')
        form.locator('[name="first_name"]').fill('David')
        form.locator('[name="last_name"]').fill('Created')
        form.locator('[name="age"]').fill('30')
        modal.locator('[bloomerp-close-modal]').click()
        expect(modal).to_be_hidden()
        self.filter_host().locator('[data-dataview-create-button]').click()
        expect(form.locator('[name="last_name"]')).to_have_value('Created')
        form.locator('button[type="submit"]:visible').first.click()
        expect(modal).to_be_hidden()
        success_message = self.page.locator('[bloomerp-component="ui-message"][data-message-type="success"]')
        expect(success_message).to_have_count(1)
        expect(self.page.locator('.message-container').filter(has_text='Object successfully created')).to_be_visible()
        expect(self.filter_host().locator('tbody')).to_contain_text('Created')
        expect(self.page.locator('body')).to_have_attribute('data-create-test-marker', 'survived')
        self.assertEqual(self.page.url, original_url)
        expect(self.filter_host().locator('[data-dataview-create-button]')).to_be_focused()
        self.filter_host().locator('[data-dataview-create-button]').click()
        expect(modal.locator('[name="first_name"]')).to_have_value('')
        expect(modal.locator('[name="last_name"]')).to_have_value('')
        expect(success_message).to_have_count(1)

    @skip('List-specific validation journey is not wired yet.')
    def test_invalid_value_feedback(self):
        """UC: Enter a nonnumeric age comparison.
        Expected Result: Show validation feedback without silently dropping the condition.
        """

    @skip('List-specific pagination journey is not wired yet.')
    def test_paginate_filtered_records(self):
        """UC: Apply a filter on a later page, then paginate.
        Expected Result: Reset the page on Apply and retain filters when paginating.
        """

    @skip('List-specific split-view journey is not wired yet.')
    def test_save_from_split_view(self):
        """UC: Edit and save a filtered record in split view.
        Expected Result: Refresh the list consistently with its active filters.
        """

    @skip('List-specific display-fields journey is not wired yet.')
    def test_change_display_fields(self):
        """UC: Change visible columns while filtering.
        Expected Result: Display the chosen columns and retain active filters.
        """
