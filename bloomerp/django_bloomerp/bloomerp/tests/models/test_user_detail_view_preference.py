import json
from types import SimpleNamespace

from django.test import RequestFactory

from bloomerp.tests.base import BaseBloomerpModelTestCase
from bloomerp.models import ApplicationField, UserDetailViewPreference
from django.contrib.contenttypes.models import ContentType
from bloomerp.router import router
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.models.workspaces.tile import Tile
from bloomerp.services.sectioned_layout_services import get_application_field_help_text

class DetailViewTabsTestCase(BaseBloomerpModelTestCase):
    # -------------------
    # TABS
    # -------------------
    def test_automatically_create_tabs(self):
        """
        Tests whether detail view tabs are automatically created for users that don't have any tabs yet
        for a particular model.
        """        
        # 1. Get a random object and its detail view URL
        obj = self.CustomerModel.objects.first()
        url = obj.get_absolute_url()
        
        # 2. Check whether the user has any detail view preferences for this model (there should be none)
        detail_view_preference = UserDetailViewPreference.objects.filter(
            user=self.admin_user,
            content_type=ContentType.objects.get_for_model(self.CustomerModel)
        ).first()
        self.assertIsNone(detail_view_preference)
        
        # 3. Simulate a request to the detail view URL with the admin user and check whether detail view preferences are created
        self.factory = RequestFactory()
        request = self.factory.get(url)
        request.user = self.admin_user
        self.client.force_login(self.admin_user)
        response = self.client.get(url)
        
        # 4. Check whether detail view preferences are created for the user and model
        detail_view_preference = UserDetailViewPreference.objects.filter(
            user=self.admin_user,
            content_type=ContentType.objects.get_for_model(self.CustomerModel)
        ).first()
        self.assertIsNotNone(detail_view_preference)
        
        # 5. Check whether the created detail view preferences have the default tabs
        self.assertTrue(len(detail_view_preference.tab_state_obj.get("top_level_order")) > 0)
                
    def test_non_existant_url_name_should_not_return_500(self):
        """
        Tests whether a non-existant URL name in the tabs configuration raises an error or is just ignored.
        """
        # 1. Create detail view preferences for the admin user and CustomerModel with a non-existant URL name in the tab configuration
        detail_view_preference = UserDetailViewPreference.objects.create(
            user=self.admin_user,
            content_type=ContentType.objects.get_for_model(self.CustomerModel),
            field_layout={},
            tab_state={
                "version": 2,
                "top_level_order": ["non_existant_tab"],
                "folders": [],
                "active": None,
            }
        )
        
        # 2. Simulate a request to the detail view URL with the admin user and check whether it returns a 200 status code (instead of a 500)
        obj = self.CustomerModel.objects.first()
        url = obj.get_absolute_url()
        
        self.factory = RequestFactory()
        request = self.factory.get(url)
        request.user = self.admin_user
        self.client.force_login(self.admin_user)
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)

    def test_tab_state_obj_normalizes_legacy_v1_shape(self):
        detail_view_preference = UserDetailViewPreference.objects.create(
            user=self.admin_user,
            content_type=ContentType.objects.get_for_model(self.CustomerModel),
            field_layout={},
            tab_state={
                "order": ["overview"],
                "active": "overview",
            },
        )

        self.assertEqual(detail_view_preference.tab_state_obj.get("version"), 2)
        self.assertEqual(detail_view_preference.tab_state_obj.get("top_level_order"), ["overview"])
        self.assertEqual(detail_view_preference.tab_state_obj.get("folders"), [])

    def test_tab_state_obj_defaults_for_invalid_state(self):
        detail_view_preference = UserDetailViewPreference.objects.create(
            user=self.admin_user,
            content_type=ContentType.objects.get_for_model(self.CustomerModel),
            field_layout={},
            tab_state="invalid",
        )

        self.assertEqual(detail_view_preference.tab_state_obj.get("version"), 2)
        self.assertEqual(detail_view_preference.tab_state_obj.get("top_level_order"), [])
        self.assertEqual(detail_view_preference.tab_state_obj.get("folders"), [])
        self.assertIsNone(detail_view_preference.tab_state_obj.get("active"))

    # -------------------
    # DETAIL VIEWS
    # -------------------
    def test_detail_layout_save_persists_row_item_shape(self):
        self.client.force_login(self.admin_user)
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        field = ApplicationField.objects.filter(content_type=content_type).first()

        response = self.client.post(
            "/components/workspaces/crud_layout_preference/",
            data=json.dumps({
                "layout_kind": "detail",
                "content_type_id": content_type.pk,
                "layout": {
                    "rows": [
                        {
                            "title": "Primary",
                            "columns": 3,
                            "items": [{"id": field.pk, "colspan": 2}],
                        }
                    ]
                },
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        preference = UserDetailViewPreference.get_or_create_for_user(self.admin_user, content_type)
        self.assertEqual(preference.field_layout_obj.rows[0].title, "Primary")
        self.assertEqual(preference.field_layout_obj.rows[0].items[0].id, field.pk)
        self.assertEqual(preference.field_layout_obj.rows[0].items[0].colspan, 2)

    def test_detail_layout_render_field_returns_fragment(self):
        self.client.force_login(self.admin_user)
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        field = ApplicationField.objects.filter(content_type=content_type).order_by("field").first()
        obj = self.CustomerModel.objects.first()

        response = self.client.get(
            "/components/workspaces/crud_layout_render_field/",
            {
                "layout_kind": "detail",
                "content_type_id": content_type.pk,
                "object_id": obj.pk,
                "field_id": field.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, field.title)

    def test_shared_layout_available_fields_route_returns_detail_items(self):
        # TODO: Add description of what this test actually does
        self.client.force_login(self.admin_user)
        content_type = ContentType.objects.get_for_model(self.CustomerModel)

        response = self.client.get(
            "/components/workspaces/crud_layout_available_fields/",
            {
                "content_type_id": content_type.pk,
                "layout_kind": "detail",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-layout-item-id", html=False)

    def test_get_application_field_help_text_reads_form_field_help_text(self):
        field = ApplicationField(field="first_name")
        field.get_form_field = lambda: SimpleNamespace(help_text="Helpful text")

        self.assertEqual(get_application_field_help_text(field), "Helpful text")

    def test_detail_layout_auto_generation_without_setup(self):
        """
        Tests whether the detail layout creates the 
        """
        # TODO: Refine test
        from bloomerp.services.sectioned_layout_services import create_default_layout
        # 1. Create a default layout
        field_layout = create_default_layout(self.CustomerModel)

        # 2. Validate 


    # -------------------
    # WORKSPACE VIEWS
    # -------------------
    def test_workspace_layout_save_persists_shape(self):
        self.client.force_login(self.admin_user)
        workspace = Workspace.get_or_create_for_user(self.admin_user)
        tile = Tile.objects.create(name="Revenue", description="Tile", schema={})

        response = self.client.post(
            "/components/workspaces/save_workspace_layout/",
            data=json.dumps({
                "workspace_id": workspace.pk,
                "layout": {
                    "rows": [
                        {
                            "title": "Metrics",
                            "columns": 4,
                            "items": [{"id": tile.pk, "colspan": 2}],
                        }
                    ]
                },
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        workspace.refresh_from_db()
        self.assertEqual(workspace.layout_obj.rows[0].title, "Metrics")
        self.assertEqual(workspace.layout_obj.rows[0].items[0].id, tile.pk)

    def test_workspace_layout_save_deduplicates_duplicate_item_ids(self):
        self.client.force_login(self.admin_user)
        workspace = Workspace.get_or_create_for_user(self.admin_user)
        tile = Tile.objects.create(name="Active deals", description="Tile", schema={})

        response = self.client.post(
            "/components/workspaces/save_workspace_layout/",
            data=json.dumps({
                "workspace_id": workspace.pk,
                "layout": {
                    "rows": [
                        {
                            "title": "Metrics",
                            "columns": 4,
                            "items": [
                                {"id": tile.pk, "colspan": 2},
                                {"id": tile.pk, "colspan": 1},
                            ],
                        },
                        {
                            "title": "Duplicate row",
                            "columns": 4,
                            "items": [{"id": tile.pk, "colspan": 3}],
                        },
                    ]
                },
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        workspace.refresh_from_db()
        item_ids = [item.id for row in workspace.layout_obj.rows for item in row.items]
        self.assertEqual(item_ids, [tile.pk])

    def test_existing_empty_detail_layout_is_seeded_with_default_items(self):
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        preference = UserDetailViewPreference.objects.create(
            user=self.admin_user,
            content_type=content_type,
            field_layout={},
            tab_state={
                "version": 2,
                "top_level_order": [],
                "folders": [],
                "active": None,
            },
        )

        repaired = UserDetailViewPreference.get_or_create_for_user(self.admin_user, content_type)
        self.assertEqual(repaired.pk, preference.pk)
        self.assertTrue(any(row.items for row in repaired.field_layout_obj.rows))

    def test_user_detail_view_handles_auto_created_one_to_many_fields(self):
        self.client.force_login(self.admin_user)

        response = self.client.get(self.admin_user.get_absolute_url())

        self.assertEqual(response.status_code, 200)

    def test_existing_empty_workspace_layout_is_seeded_with_dummy_items(self):
        workspace = Workspace.objects.create(
            user=self.admin_user,
            module_id="",
            sub_module_id="",
            layout={},
        )

        repaired = Workspace.get_or_create_for_user(self.admin_user)
        self.assertEqual(repaired.pk, workspace.pk)
        self.assertTrue(any(row.items for row in repaired.layout_obj.rows))
    
    
