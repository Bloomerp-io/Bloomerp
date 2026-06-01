import json
from types import SimpleNamespace

from django.test import RequestFactory

from bloomerp.tests.base import BaseBloomerpModelTestCase
from bloomerp.models import ApplicationField, FieldPolicy, UserDetailViewPreference
from django.contrib.contenttypes.models import ContentType
from bloomerp.router import router
from bloomerp.models.base_bloomerp_model import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.definition import BloomerpModelConfig
from bloomerp.models.forms.form import Form as BloomerpForm
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
            layout={},
            tab_state={
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

    def test_tab_state_obj_defaults_for_invalid_state(self):
        detail_view_preference = UserDetailViewPreference.objects.create(
            user=self.admin_user,
            content_type=ContentType.objects.get_for_model(self.CustomerModel),
            layout={},
            tab_state="invalid",
        )

        self.assertEqual(detail_view_preference.tab_state_obj.get("top_level_order"), [])
        self.assertEqual(detail_view_preference.tab_state_obj.get("folders"), [])
        self.assertIsNone(detail_view_preference.tab_state_obj.get("active"))

    def test_get_or_create_promotes_existing_preference_when_none_selected(self):
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        preference = UserDetailViewPreference.objects.create(
            user=self.admin_user,
            content_type=content_type,
            layout={},
        )
        UserDetailViewPreference.objects.filter(pk=preference.pk).update(selected=False)

        resolved = UserDetailViewPreference.get_or_create_for_user(self.admin_user, content_type)

        self.assertEqual(resolved.pk, preference.pk)
        self.assertTrue(resolved.selected)

    # -------------------
    # DETAIL VIEWS
    # -------------------
    def test_detail_layout_save_persists_row_item_shape(self):
        self.client.force_login(self.admin_user)
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        field = ApplicationField.objects.filter(
            content_type=content_type,
            field="first_name",
        ).first()

        response = self.client.post(
            "/components/workspaces/detail_layout_preference/",
            data=json.dumps({
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
        self.assertEqual(preference.layout_obj.rows[0].title, "Primary")
        self.assertEqual(preference.layout_obj.rows[0].items[0].id, str(field.pk))
        self.assertEqual(preference.layout_obj.rows[0].items[0].colspan, 2)

    def test_detail_layout_save_persists_item_config(self):
        self.client.force_login(self.admin_user)
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        field = ApplicationField.objects.filter(
            content_type=content_type,
            field="first_name",
        ).first()

        response = self.client.post(
            "/components/workspaces/detail_layout_preference/",
            data=json.dumps({
                "content_type_id": content_type.pk,
                "layout": {
                    "rows": [
                        {
                            "title": "Primary",
                            "columns": 3,
                            "items": [
                                {
                                    "id": field.pk,
                                    "colspan": 2,
                                    "config": {
                                        "display": "compact",
                                        "inline_fields": ["activity_type", "hours"],
                                    },
                                }
                            ],
                        }
                    ]
                },
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        preference = UserDetailViewPreference.get_or_create_for_user(self.admin_user, content_type)
        item = preference.layout_obj.rows[0].items[0]
        self.assertEqual(item.config["display"], "compact")
        self.assertEqual(item.config["inline_fields"], ["activity_type", "hours"])

    def test_field_display_options_updates_layout_item_config(self):
        self.client.force_login(self.admin_user)
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        field = ApplicationField.objects.get(
            content_type=content_type,
            field="first_name",
        )
        preference = UserDetailViewPreference.objects.create(
            user=self.admin_user,
            content_type=content_type,
            layout={
                "rows": [
                    {
                        "title": "Primary",
                        "columns": 2,
                        "items": [{"id": field.pk, "colspan": 1, "config": {}}],
                    }
                ]
            },
        )

        response = self.client.post(
            f"/components/field_display_options/{field.pk}/",
            {
                "preference_id": preference.pk,
                "preference_scope": "detail",
                "label": "Preferred name",
            },
        )

        self.assertEqual(response.status_code, 200)
        preference.refresh_from_db()
        item = preference.layout_obj.rows[0].items[0]
        self.assertEqual(item.config["label"], "Preferred name")

    def test_field_display_options_updates_form_layout_item_config(self):
        self.client.force_login(self.admin_user)
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        field = ApplicationField.objects.get(
            content_type=content_type,
            field="first_name",
        )
        form_object = BloomerpForm.objects.create(
            name="Customer signup",
            content_type=content_type,
            layout={
                "rows": [
                    {
                        "title": "Primary",
                        "columns": 2,
                        "items": [{"id": field.pk, "colspan": 1, "config": {}}],
                    }
                ]
            },
        )
        layout_object_content_type = ContentType.objects.get_for_model(BloomerpForm)

        response = self.client.post(
            f"/components/field_display_options/{field.pk}/",
            {
                "layout_object_content_type_id": layout_object_content_type.pk,
                "layout_object_id": form_object.pk,
                "layout_mode": "form",
                "layout_edit_mode": "true",
                "label": "Public first name",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'id="layout-field-{field.pk}"', html=False)
        self.assertContains(response, 'hx-swap-oob="outerHTML"', html=False)
        form_object.refresh_from_db()
        item = form_object.layout_obj.rows[0].items[0]
        self.assertEqual(item.config["label"], "Public first name")

    def test_field_display_options_returns_oob_field_swap_for_detail_object(self):
        self.client.force_login(self.admin_user)
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        field = ApplicationField.objects.get(
            content_type=content_type,
            field="first_name",
        )
        obj = self.CustomerModel.objects.first()
        preference = UserDetailViewPreference.objects.create(
            user=self.admin_user,
            content_type=content_type,
            layout={
                "rows": [
                    {
                        "title": "Primary",
                        "columns": 2,
                        "items": [{"id": field.pk, "colspan": 1, "config": {}}],
                    }
                ]
            },
        )

        response = self.client.post(
            f"/components/field_display_options/{field.pk}/",
            {
                "preference_id": preference.pk,
                "preference_scope": "detail",
                "object_id": obj.pk,
                "label": "Preferred name",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'id="layout-field-{field.pk}"', html=False)
        self.assertContains(response, 'hx-swap-oob="outerHTML"', html=False)
        self.assertContains(response, "Preferred name", html=False)
        trigger = response.headers.get("HX-Trigger-After-Swap", "")
        self.assertIn("bloomerp:close-modal", trigger)
        self.assertIn("bloomerp:layout-field-updated", trigger)

    def test_one_to_many_display_options_show_required_fields(self):
        self.client.force_login(self.admin_user)
        content_type = ContentType.objects.get_for_model(FieldPolicy)
        field = ApplicationField.objects.get(
            content_type=content_type,
            field="policies",
        )
        preference = UserDetailViewPreference.objects.create(
            user=self.admin_user,
            content_type=content_type,
            layout={
                "rows": [
                    {
                        "title": "Primary",
                        "columns": 1,
                        "items": [{"id": field.pk, "colspan": 1, "config": {}}],
                    }
                ]
            },
        )

        response = self.client.get(
            f"/components/field_display_options/{field.pk}/",
            {
                "preference_id": preference.pk,
                "preference_scope": "detail",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Name", html=False)
        self.assertContains(response, "Row Policy", html=False)
        self.assertContains(response, "Required", html=False)
        self.assertNotContains(response, "Field Policy", html=False)

    def test_one_to_many_display_options_preserve_inline_field_order(self):
        self.client.force_login(self.admin_user)
        content_type = ContentType.objects.get_for_model(FieldPolicy)
        field = ApplicationField.objects.get(
            content_type=content_type,
            field="policies",
        )
        preference = UserDetailViewPreference.objects.create(
            user=self.admin_user,
            content_type=content_type,
            layout={
                "rows": [
                    {
                        "title": "Primary",
                        "columns": 1,
                        "items": [{"id": field.pk, "colspan": 1, "config": {}}],
                    }
                ]
            },
        )

        response = self.client.post(
            f"/components/field_display_options/{field.pk}/",
            {
                "preference_id": preference.pk,
                "preference_scope": "detail",
                "inline_fields": ["description", "name", "row_policy"],
            },
        )

        self.assertEqual(response.status_code, 200)
        preference.refresh_from_db()
        item = preference.layout_obj.rows[0].items[0]
        self.assertEqual(item.config["inline_fields"], ["description", "name", "row_policy"])

    def test_one_to_many_display_options_keep_required_fields_selected(self):
        self.client.force_login(self.admin_user)
        content_type = ContentType.objects.get_for_model(FieldPolicy)
        field = ApplicationField.objects.get(
            content_type=content_type,
            field="policies",
        )
        preference = UserDetailViewPreference.objects.create(
            user=self.admin_user,
            content_type=content_type,
            layout={
                "rows": [
                    {
                        "title": "Primary",
                        "columns": 1,
                        "items": [{"id": field.pk, "colspan": 1, "config": {}}],
                    }
                ]
            },
        )

        response = self.client.post(
            f"/components/field_display_options/{field.pk}/",
            {
                "preference_id": preference.pk,
                "preference_scope": "detail",
                "inline_fields": ["description"],
            },
        )

        self.assertEqual(response.status_code, 200)
        preference.refresh_from_db()
        item = preference.layout_obj.rows[0].items[0]
        self.assertEqual(item.config["inline_fields"], ["description", "name", "row_policy"])

    def test_detail_layout_render_field_returns_fragment(self):
        self.client.force_login(self.admin_user)
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        field = ApplicationField.objects.filter(content_type=content_type).order_by("field").first()
        obj = self.CustomerModel.objects.first()

        response = self.client.get(
            "/components/workspaces/crud_layout_render_field/",
            {
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
            "/components/workspaces/detail_layout_available_fields/",
            {
                "content_type_id": content_type.pk,
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
        layout = create_default_layout(self.CustomerModel)

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
                "workspace_id": str(workspace.pk),
                "layout": {
                    "rows": [
                        {
                            "title": "Metrics",
                            "columns": 4,
                            "items": [{"id": str(tile.pk), "colspan": 2}],
                        }
                    ]
                },
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        workspace.refresh_from_db()
        self.assertEqual(workspace.layout_obj.rows[0].title, "Metrics")
        self.assertEqual(workspace.layout_obj.rows[0].items[0].id, str(tile.pk))

    def test_workspace_layout_save_deduplicates_duplicate_item_ids(self):
        self.client.force_login(self.admin_user)
        workspace = Workspace.get_or_create_for_user(self.admin_user)
        tile = Tile.objects.create(name="Active deals", description="Tile", schema={})

        response = self.client.post(
            "/components/workspaces/save_workspace_layout/",
            data=json.dumps({
                "workspace_id": str(workspace.pk),
                "layout": {
                    "rows": [
                        {
                            "title": "Metrics",
                            "columns": 4,
                            "items": [
                                {"id": str(tile.pk), "colspan": 2},
                                {"id": str(tile.pk), "colspan": 1},
                            ],
                        },
                        {
                            "title": "Duplicate row",
                            "columns": 4,
                            "items": [{"id": str(tile.pk), "colspan": 3}],
                        },
                    ]
                },
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        workspace.refresh_from_db()
        item_ids = [item.id for row in workspace.layout_obj.rows for item in row.items]
        self.assertEqual(item_ids, [str(tile.pk)])

    def test_existing_empty_detail_layout_is_seeded_with_default_items(self):
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        preference = UserDetailViewPreference.objects.create(
            user=self.admin_user,
            content_type=content_type,
            layout={},
            tab_state={
                "top_level_order": [],
                "folders": [],
                "active": None,
            },
        )

        repaired = UserDetailViewPreference.get_or_create_for_user(self.admin_user, content_type)
        self.assertEqual(repaired.pk, preference.pk)
        self.assertTrue(any(row.items for row in repaired.layout_obj.rows))

    def test_default_detail_layout_does_not_append_unconfigured_fields(self):
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        configured_field = ApplicationField.objects.get(
            content_type=content_type,
            field="first_name",
        )
        original_config = getattr(self.CustomerModel, "bloomerp_config", None)
        self.CustomerModel.bloomerp_config = BloomerpModelConfig(
            layout=FieldLayout(
                rows=[
                    LayoutRow(
                        title="Primary",
                        columns=2,
                        items=[LayoutItem(id="first_name", colspan=2)],
                    )
                ]
            )
        )

        try:
            preference = UserDetailViewPreference.create_default_for_user(self.admin_user, content_type)

            self.assertEqual(len(preference.layout_obj.rows), 1)
            self.assertEqual(preference.layout_obj.rows[0].title, "Primary")
            self.assertEqual(
                [item.id for item in preference.layout_obj.rows[0].items],
                [str(configured_field.pk)],
            )
        finally:
            self.CustomerModel.bloomerp_config = original_config

    def test_user_detail_view_handles_auto_created_one_to_many_fields(self):
        self.client.force_login(self.admin_user)

        response = self.client.get(self.admin_user.get_absolute_url())

        self.assertEqual(response.status_code, 200)

    
    
    
