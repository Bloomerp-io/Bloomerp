from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from playwright.sync_api import Locator, expect

from bloomerp.models.application_field import ApplicationField
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.models.workspaces.tile import Tile
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.tests.base import E2ERequestScenario, e2e_test_case
from bloomerp.tests.e2e.mixins.filters_e2e_mixin import FilterE2EMixin
from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig, AnalyticsTileFilter, FieldConfig
from bloomerp.workspaces.dataview_tile.model import DataViewTileConfig


class TestBloomerpHomeViewE2E(FilterE2EMixin, e2e_test_case.BloomerpE2ETestCase):
    """Run shared filter journeys against analytics and dataview tiles together."""

    scope = 'workspace'
    filter_field_path = 'shared:first_name'
    auto_create_customers = False

    def prepare_filter_host(self) -> None:
        Workspace.objects.filter(user__in=[self.admin_user, self.normal_user]).delete()
        Tile.objects.filter(name__startswith='Filter E2E ').delete()
        self.CustomerModel.objects.all().delete()
        for name in ('David', 'Kyle', 'Alex'):
            self.create_customer(name, 'Example', 30)
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        UserListViewPreference.objects.filter(content_type=content_type).delete()
        first_name = ApplicationField.get_by_field(self.CustomerModel, 'first_name')
        preference = UserListViewPreference.objects.create(
            user=self.admin_user, content_type=content_type, view_type='table',
            display_fields={'table': [first_name.pk]},
        )
        analytics = AnalyticsTileConfig(
            query="SELECT 'David' AS first_name UNION ALL SELECT 'Kyle' UNION ALL SELECT 'Alex'",
            type='TABLE', fields={'columns': [FieldConfig(name='first_name')]},
            filters=[AnalyticsTileFilter(field='first_name', type='text')],
        )
        dataview = DataViewTileConfig(
            content_type_id=content_type.pk, list_view_preference_id=preference.pk, actions=[],
        )
        self.tiles = [
            Tile.objects.create(name='Filter E2E analytics', type='ANALYTICS_TILE', schema=analytics.model_dump(mode='json')),
            Tile.objects.create(name='Filter E2E dataview', type='DATAVIEW_TILE', schema=dataview.model_dump(mode='json')),
        ]
        self.workspace = Workspace.objects.create(
            user=self.admin_user, name='Filter workspace', selected=True,
            layout={'rows': [{'columns': 2, 'items': [
                {'id': str(tile.pk), 'colspan': 1} for tile in self.tiles
            ]}]},
        )

    def filter_page_url(self) -> str:
        return reverse('bloomerp_home_view')

    def filter_scope_id(self) -> str:
        return str(self.workspace.pk)

    def filter_host(self) -> Locator:
        return self.page.locator(f'[bloomerp-component="workspace-container"][data-workspace-id="{self.workspace.pk}"]')

    def filter_default_host(self):
        return self.workspace

    def share_filter_host(self):
        self.workspace.user = self.normal_user
        self.workspace.save()
        self.workspace.shared_with_users.add(self.admin_user)
        Workspace.objects.create(user=self.admin_user, source_object=self.workspace, selected=True)

    def assert_filter_results(self, first_name: str | None) -> None:
        expected = [first_name] if first_name else ['David', 'Kyle', 'Alex']
        for tile in self.tiles:
            rows = self.filter_host().locator(f'[data-layout-item-id="{tile.pk}"]').first.locator('tbody tr')
            expect(rows).to_have_count(len(expected))
            for name in expected:
                expect(rows.get_by_role('cell', name=name, exact=True)).to_have_count(1)

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        return self.get_filter_test_scenarios()
