import json

from bs4 import BeautifulSoup
from django import forms
from django.contrib.contenttypes.models import ContentType
from django.template.loader import render_to_string
from django.test import RequestFactory
from django.http import HttpResponse
from django.urls import reverse
from types import SimpleNamespace
from unittest.mock import patch

from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.models import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.definition import get_default_dataview_actions
from bloomerp.models.workspaces.tile import Tile
from bloomerp.components.layout.render_layout_item import _tile
from bloomerp.services.workspace_services import (
    _localize_generated_module_links,
    _tile_display_metadata,
    render_tile_to_string,
)
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels
from bloomerp.workspaces.links_tile.model import Link, LinkTileConfig
from bloomerp.workspaces.links_tile.render import LinksTileRenderer
from bloomerp.workspaces.dataview_tile.form import DataViewTileForm
from bloomerp.workspaces.dataview_tile.model import DataViewTileConfig
from bloomerp.workspaces.dataview_tile.render import DataViewTileRenderer
from bloomerp.workspaces.canvas_tile.model import CanvasTileConfig
from bloomerp.workspaces.canvas_tile.render import CanvasTileRenderer
from bloomerp.workspaces.text_tile.model import TextTileConfig
from bloomerp.workspaces.text_tile.render import render_html
from bloomerp.workspaces.tiles import TileType
from bloomerp.modules.definition import ModuleConfig
from bloomerp.workspaces.utils import UserParameterResolver
from bloomerp.widgets.code_editor_widget import CodeEditorWidget
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget
from bloomerp.views.workspaces.create_tile import CREATE_TILE_SESSION_KEY
from bloomerp.views.workspaces.base import BaseWorkspaceView


class WorkspaceTileRenderingTests(BaseBloomerpTestCaseWithModels):
    auto_create_customers = False

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def test_generated_module_tile_metadata_is_localized_without_mutating_storage(self):
        module = ModuleConfig(
            id="users",
            code="users",
            name="Users",
            route_path="users",
            owner_app_label="bloomerp",
        )
        tile = SimpleNamespace(
            auto_generated=True,
            name="Users",
            description="Navigate to the 'Users' module.",
            schema={"links": [{"url": "/users/", "name": "Users"}]},
        )
        links = [Link(url="/users/", name="Users", is_internal=True)]

        with (
            patch(
                "bloomerp.services.workspace_services.module_registry.get_all",
                return_value={"users": module},
            ),
            patch(
                "bloomerp.modules.definition.pgettext",
                side_effect=lambda _context, message: (
                    "Utilizadores" if message == "Users" else message
                ),
            ),
            patch(
                "bloomerp.services.workspace_services.gettext",
                side_effect=lambda message: (
                    "Navegar para o módulo '{module}'."
                    if message == "Navigate to the '{module}' module."
                    else message
                ),
            ),
        ):
            title, description = _tile_display_metadata(tile)
            _localize_generated_module_links(links)

        self.assertEqual(title, "Utilizadores")
        self.assertEqual(description, "Navegar para o módulo 'Utilizadores'.")
        self.assertEqual(links[0].name, "Utilizadores")
        self.assertEqual(tile.name, "Users")
        self.assertEqual(tile.schema["links"][0]["name"], "Users")

    def test_text_tile_renders_template_content(self):
        """
        Use case: A workspace text tile is rendered from its saved tile configuration.
        Expected result: The tile template renders content instead of surfacing a missing template path.
        """
        # 1. Create a text tile with visible markdown content.
        tile = Tile.objects.create(
            name="KPI tile",
            description="",
            type=TileType.TEXT_TILE.name,
            schema={"markdown": "Visible workspace tile"},
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )
        request = self.factory.get("/")
        request.user = self.admin_user

        # 2. Render the tile through the workspace rendering service.
        html = render_tile_to_string(tile, request)

        # 3. Verify the template content renders instead of the template file name.
        self.assertIn("Visible workspace tile", html)
        self.assertNotIn("cotton/workspaces/tiles/text.html", html)

    @patch(
        "bloomerp.services.workspace_services.render_tile_to_string",
        return_value="<p>Rendered tile body</p>",
    )
    def test_layout_tile_endpoint_wraps_sidebar_insertions(self, _render_tile):
        tile = Tile.objects.create(
            name="Sidebar tile",
            description="",
            type=TileType.TEXT_TILE.name,
            schema={"markdown": "Sidebar tile"},
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )
        request = self.factory.get(
            "/",
            {
                "tile_id": tile.pk,
                "config": '{"display": "compact"}',
                "max_cols": "6",
            },
        )
        request.user = self.admin_user

        response = _tile(request, ContentType.objects.get_for_model(Tile))
        soup = BeautifulSoup(response.content, "html.parser")

        rendered_tile = soup.find(attrs={"bloomerp-component": "workspace-tile"})
        self.assertIsNotNone(rendered_tile)
        self.assertEqual(rendered_tile["data-layout-item-id"], str(tile.pk))
        self.assertEqual(
            json.loads(rendered_tile["data-layout-item-config"]),
            {"display": "compact"},
        )
        self.assertEqual(rendered_tile["data-max-cols"], "6")
        self.assertIn("layout-item--bordered", rendered_tile.get("class", []))
        self.assertIn("Rendered tile body", rendered_tile.get_text())

    @patch("bloomerp.services.workspace_services.render_tile_to_string")
    def test_workspace_view_defers_initial_tile_content_rendering(self, render_tile):
        """
        Use case: A workspace with tiles is opened.
        Expected result: The initial response contains tile shells without executing tile queries.
        """
        # 1. Create a tile whose renderer would normally produce the body.
        tile = Tile.objects.create(
            name="Initial tile",
            description="",
            type=TileType.TEXT_TILE.name,
            schema={"markdown": "Initial tile"},
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )
        request = self.factory.get("/")
        request.user = self.admin_user
        workspace = SimpleNamespace(
            effective_preference=SimpleNamespace(pk="workspace-1")
        )

        class TestWorkspaceView(BaseWorkspaceView):
            def get_module_id(self):
                return None

            def get_workspace(self):
                return workspace

            def get_layout(self):
                return FieldLayout(
                    rows=[
                        LayoutRow(
                            columns=4,
                            items=[LayoutItem(id=str(tile.pk), colspan=2)],
                        )
                    ]
                )

        view = TestWorkspaceView()
        view.request = request

        # 2. Transform the workspace layout for the initial response.
        item = view.get_transformed_layout().rows[0].items[0]

        # 3. Verify the tile shell is complete while its expensive body is deferred.
        self.assertEqual(item.component_name, "workspace-tile")
        self.assertEqual(item.content, "")
        self.assertEqual(item.colspan, 2)
        self.assertTrue(item.border)
        render_tile.assert_not_called()

    def test_table_pagination_replaces_only_the_layout_item_body(self):
        html = render_to_string(
            "cotton/features/workspaces/tiles/table.html",
            {
                "payload": {"columns": ["Title"], "rows": [["First row"]]},
                "tile_id": "tile-1",
                "url": "/components/layout/render-layout-item/1/",
                "current_page": 1,
                "total_pages": 2,
                "has_previous": False,
                "has_next": True,
                "previous_page_number": 0,
                "next_page_number": 2,
                "pagination_pages": [1, 2],
                "show_global_pagination": True,
                "result_start": 1,
                "result_end": 10,
                "result_count": 11,
                "pagination_querystring": "tile_id=tile-1&colspan=1&max_cols=4",
            },
        )
        soup = BeautifulSoup(html, "html.parser")

        pagination = soup.find("nav", attrs={"aria-label": "Pagination"})
        self.assertIsNotNone(pagination)
        self.assertEqual(pagination["hx-target"], "closest [data-layout-item-body]")
        self.assertEqual(pagination["hx-select"], "[data-layout-item-body]")
        self.assertEqual(pagination["hx-swap"], "outerHTML")
        self.assertNotIn(f'#layout-field-tile-1', html)

    def test_data_view_tile_is_registered_with_its_builder_and_renderer(self):
        """
        Use case: A user opens the workspace tile type selector.
        Expected result: Data View is an available tile backed by its form, config, and renderer.
        """
        # 1. Resolve the registered data-view tile definition.
        definition = TileType.DATAVIEW_TILE.value

        # 2. Verify every runtime dependency is registered.
        self.assertIs(definition.form_cls, DataViewTileForm)
        self.assertIs(definition.model, DataViewTileConfig)
        self.assertIs(definition.render_cls, DataViewTileRenderer)

    def test_data_view_tile_form_uses_requested_widgets_and_nullable_preference(self):
        """
        Use case: A user configures a data-view tile for a permitted model.
        Expected result: The model uses ForeignFieldWidget and the optional preference uses a normal select.
        """
        # 1. Create a saved preference for a model the admin user may view.
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        preference = UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=content_type,
            name="Workspace customers",
        )

        # 2. Build the tile form for that content type.
        form = DataViewTileForm(
            user=self.admin_user,
            initial={"content_type_id": content_type.pk},
        )

        # 3. Verify the widget contracts and scoped preference choices.
        self.assertIsInstance(form.fields["content_type_id"].widget, ForeignFieldWidget)
        self.assertIsInstance(form.fields["list_view_preference_id"].widget, forms.Select)
        self.assertNotIsInstance(
            form.fields["list_view_preference_id"].widget,
            ForeignFieldWidget,
        )
        self.assertFalse(form.fields["list_view_preference_id"].required)
        self.assertIn(preference, form.fields["list_view_preference_id"].queryset)
        self.assertIsInstance(
            form.fields["initial_query_params"].widget,
            CodeEditorWidget,
        )

    @patch("bloomerp.workspaces.dataview_tile.form.get_model_config", return_value=None)
    def test_data_view_tile_form_uses_default_actions_without_model_config(
        self,
        _get_model_config,
    ):
        """A model without view settings offers and selects the standard actions."""
        content_type = ContentType.objects.get_for_model(self.CustomerModel)

        form = DataViewTileForm(
            user=self.admin_user,
            initial={"content_type_id": content_type.pk, "actions": None},
        )

        default_ids = [action.id for action in get_default_dataview_actions()]
        available_ids = [
            action_id
            for action_id in default_ids
            if action_id not in {"display-options", "select-preference"}
        ]
        self.assertEqual(
            [action_id for action_id, _label in form.fields["actions"].choices],
            available_ids,
        )
        self.assertNotIn("display-options", available_ids)
        self.assertNotIn("select-preference", available_ids)
        self.assertEqual(form.initial["actions"], available_ids)

    @patch("bloomerp.workspaces.dataview_tile.form.get_model_config")
    def test_data_view_tile_form_uses_actions_from_model_config(
        self,
        get_model_config_mock,
    ):
        """Configured model actions become the tile's available default choices."""
        get_model_config_mock.return_value = SimpleNamespace(
            model_view_settings=SimpleNamespace(
                dataview_actions=[
                    SimpleNamespace(id="approve", label="Approve"),
                    SimpleNamespace(id="display-options"),
                    SimpleNamespace(id="select-preference"),
                    SimpleNamespace(id="archive"),
                ]
            )
        )
        content_type = ContentType.objects.get_for_model(self.CustomerModel)

        form = DataViewTileForm(
            user=self.admin_user,
            initial={"content_type_id": content_type.pk, "actions": None},
        )

        self.assertEqual(
            list(form.fields["actions"].choices),
            [("approve", "Approve"), ("archive", "Archive")],
        )
        self.assertEqual(form.initial["actions"], ["approve", "archive"])

    def test_data_view_tile_form_saves_a_null_list_view_preference(self):
        """
        Use case: A user chooses a model but leaves the list-view preference empty.
        Expected result: The tile config stores the content type and a null preference.
        """
        # 1. Submit the builder form without a preference.
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        form = DataViewTileForm(
            data={
                "content_type_id": content_type.pk,
                "list_view_preference_id": "",
                "initial_query_params": '{"status": "active", "priority__gte": 2}',
            },
            user=self.admin_user,
        )

        # 2. Apply the registered form operation to an empty config.
        operation = DataViewTileConfig.get_operation("set_form")
        response = operation.handler.handle(DataViewTileConfig.get_default(), form)

        # 3. Verify the nullable value is persisted in the configuration.
        self.assertEqual(response.config.content_type_id, content_type.pk)
        self.assertIsNone(response.config.list_view_preference_id)
        self.assertEqual(
            response.config.initial_query_params,
            {"status": "active", "priority__gte": 2},
        )

    def test_data_view_tile_form_rejects_non_object_query_parameters(self):
        """Initial query parameters must be a mapping of query keys to values."""
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        form = DataViewTileForm(
            data={
                "content_type_id": content_type.pk,
                "list_view_preference_id": "",
                "initial_query_params": '["status", "active"]',
            },
            user=self.admin_user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("initial_query_params", form.errors)

    def test_data_view_tile_builder_persists_form_configuration(self):
        """
        Use case: A user changes the data-view tile builder form.
        Expected result: The preview component validates and persists the form-backed config.
        """
        # 1. Start a data-view tile builder session and sign in.
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        self.client.force_login(self.admin_user)
        session = self.client.session
        session[CREATE_TILE_SESSION_KEY] = {
            "tile_type": TileType.DATAVIEW_TILE.name,
            "config": DataViewTileConfig.get_default().model_dump(),
        }
        session.save()

        # 2. Submit the default builder form with no saved preference selected.
        response = self.client.post(
            reverse("preview_workspace_tile"),
            data={
                "operation": "set_form",
                "content_type_id": content_type.pk,
                "list_view_preference_id": "",
            },
        )

        # 3. Verify the component accepted and persisted the nullable configuration.
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-layout-item-id="preview"', html=False)
        self.assertContains(response, 'bloomerp-component="workspace-tile"', html=False)
        config = self.client.session[CREATE_TILE_SESSION_KEY]["config"]
        self.assertEqual(config["content_type_id"], content_type.pk)
        self.assertIsNone(config["list_view_preference_id"])

    @patch("bloomerp.workspaces.dataview_tile.render.dataview")
    def test_data_view_tile_renderer_uses_configured_available_preference(self, data_view_mock):
        """
        Use case: A tile is configured with a saved list-view preference.
        Expected result: Rendering uses that preference without selecting it globally for the user.
        """
        # 1. Create selected and tile-specific preferences for the same model.
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        selected = UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=content_type,
            name="Current preference",
            selected=True,
        )
        tile_preference = UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=content_type,
            name="Tile preference",
        )
        request = self.factory.get("/")
        request.user = self.admin_user
        data_view_mock.return_value = HttpResponse("Rendered data view")

        # 2. Render the tile with the non-selected preference.
        html = DataViewTileRenderer.render(
            DataViewTileConfig(
                content_type_id=content_type.pk,
                list_view_preference_id=tile_preference.pk,
                actions=["filter", "export"],
            ),
            request,
        )

        # 3. Verify the configured preference was passed through and selection was unchanged.
        self.assertEqual(html, "Rendered data view")
        self.assertEqual(data_view_mock.call_args.kwargs["preference"], tile_preference)
        self.assertEqual(
            data_view_mock.call_args.kwargs["actions"],
            ["filter", "export"],
        )
        selected.refresh_from_db()
        tile_preference.refresh_from_db()
        self.assertTrue(selected.selected)
        self.assertFalse(tile_preference.selected)

    @patch("bloomerp.workspaces.dataview_tile.render.dataview")
    def test_data_view_tile_renderer_applies_initial_query_parameters(
        self,
        data_view_mock,
    ):
        """Configured filters seed the request without replacing live parameters."""
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        request = self.factory.get(
            "/",
            {
                "status": "changed",
                "page": "2",
                "tile_id": "tile-1",
            },
        )
        request.user = self.admin_user
        data_view_mock.return_value = HttpResponse("Rendered data view")

        html = DataViewTileRenderer.render(
            DataViewTileConfig(
                content_type_id=content_type.pk,
                initial_query_params={
                    "status": "initial",
                    "category": ["one", "two"],
                    "empty": None,
                },
            ),
            request,
        )

        self.assertEqual(html, "Rendered data view")
        self.assertEqual(request.GET["status"], "changed")
        self.assertEqual(request.GET["page"], "2")
        self.assertEqual(request.GET.getlist("category"), ["one", "two"])
        self.assertNotIn("empty", request.GET)
        self.assertNotIn("tile_id", request.GET)
    def test_saved_canvas_tile_renders_state_height_and_save_url(self):
        """
        Use case: A saved canvas tile is rendered after a user has drawn on it.
        Expected result: The canvas receives its saved state, configured height, and persistence URL.
        """
        # 1. Create a canvas tile with persisted Excalidraw state and a custom height.
        tile = Tile.objects.create(
            name="Planning canvas",
            description="",
            type=TileType.CANVAS_TILE.name,
            schema={"content": {"elements": [{"id": "shape-1"}]}, "height": 640},
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )
        request = self.factory.get("/")
        request.user = self.admin_user

        # 2. Render the saved tile through the workspace rendering service.
        html = render_tile_to_string(tile, request)
        soup = BeautifulSoup(html, "html.parser")
        canvas = soup.find(attrs={"bloomerp-component": "workspace-tile-canvas"})

        # 3. Verify the persisted state and save context are present.
        self.assertIsNotNone(canvas)
        self.assertEqual(canvas["style"], "height: 640px;")
        self.assertIn('"shape-1"', canvas["data-initial-state"])
        self.assertEqual(canvas["data-save-url"], f"/api/tiles/{tile.pk}/canvas-state/")

    def test_canvas_preview_does_not_render_save_url(self):
        """
        Use case: A canvas is rendered in the tile builder before a Tile exists.
        Expected result: The preview has no persistence URL and cannot send state updates.
        """
        # 1. Render a canvas config directly, matching the builder preview path.
        request = self.factory.get("/")
        request.user = self.admin_user
        html = CanvasTileRenderer.render(CanvasTileConfig(height=512), request)
        canvas = BeautifulSoup(html, "html.parser").find(
            attrs={"bloomerp-component": "workspace-tile-canvas"}
        )

        # 2. Verify height still applies while persistence remains disabled.
        self.assertIsNotNone(canvas)
        self.assertEqual(canvas["style"], "height: 512px;")
        self.assertNotIn("data-save-url", canvas.attrs)

    def test_text_tile_renders_sanitized_editor_html(self):
        html = render_html('<h2>Notes</h2><p>Visible content</p><script>alert("xss")</script>')

        self.assertIn("<h2", html)
        self.assertIn("Visible content", html)
        self.assertNotIn("<script", html)

    def test_text_tile_editor_has_valid_htmx_update_expression(self):
        html = render_to_string(
            "components/workspaces/tiles/builders/text.html",
            {"config": TextTileConfig(markdown="<p>Initial content</p>")},
        )
        soup = BeautifulSoup(html, "html.parser")
        editor_request = soup.find(attrs={"hx-trigger": "bloomerp:widget-change delay:250ms"})

        self.assertIsNotNone(editor_request)
        self.assertIn("JSON.stringify", editor_request["hx-vars"])
        self.assertIn("[data-text-editor-input=true]", editor_request["hx-vars"])

    def test_user_parameter_resolver_replaces_current_user_attribute(self):
        resolver = UserParameterResolver(self.admin_user)

        rendered = resolver.resolve("/employees/?user={{ current_user.id }}")

        self.assertEqual(rendered, f"/employees/?user={self.admin_user.id}")

    def test_user_parameter_resolver_replaces_current_user_with_spaces(self):
        resolver = UserParameterResolver(self.normal_user)

        rendered = resolver.resolve("/employees/?user={{   current_user   }}")

        self.assertEqual(rendered, f"/employees/?user={self.normal_user.pk}")

    def test_link_tile_resolves_current_user_parameters(self):
        """
        Use case: A link tile URL contains a current-user parameter.
        Expected result: Rendering resolves the URL without mutating the saved configuration.
        """
        # 1. Create a link with a current-user parameter.
        config = LinkTileConfig(
            links=[
                Link(
                    url="/employees/?user={{ current_user.id }}",
                    name="Employees",
                    is_internal=True,
                )
            ]
        )
        request = self.factory.get("/")
        request.user = self.admin_user

        # 2. Render the tile.
        html = LinksTileRenderer.render(config, request)

        # 3. Verify the resolved output and unchanged source configuration.
        self.assertIn(f'href="/employees/?user={self.admin_user.id}"', html)
        self.assertIn(f'hx-get="{resolved_url}"', html)
        self.assertIn('hx-target="#main-content"', html)
        self.assertIn('hx-push-url="true"', html)
        self.assertIn('hx-swap="innerHTML"', html)
        self.assertEqual(config.links[0].url, "/employees/?user={{ current_user.id }}")

    def test_link_tile_renders_nested_folders(self):
        """
        Use case: A link tile contains nested folders.
        Expected result: Folders render as collapsible levels and the nested link remains navigable.
        """
        # 1. Create two nested folders containing a link.
        config = LinkTileConfig(
            links=[
                Link(
                    name="Sales",
                    is_folder=True,
                    children=[
                        Link(
                            name="Reports",
                            is_folder=True,
                            children=[Link(url="/sales/report/", name="Monthly report", is_internal=True)],
                        )
                    ],
                )
            ]
        )
        request = self.factory.get("/")
        request.user = self.admin_user

        # 2. Render the tile.
        html = LinksTileRenderer.render(config, request)

        # 3. Verify collapsible hierarchy, progressive indentation, and the nested link.
        self.assertEqual(html.count("<details"), 2)
        self.assertGreaterEqual(html.count("ml-4"), 2)
        self.assertIn('href="/sales/report/"', html)
        self.assertIn("Monthly report", html)

    def test_link_tile_renders_optional_item_icons(self):
        """
        Use case: A link tile folder and link have custom icons.
        Expected result: Both configured icons appear in the rendered tile.
        """
        # 1. Create a folder and nested link with custom icons.
        config = LinkTileConfig(
            links=[
                Link(
                    name="Sales",
                    icon="fa-solid fa-briefcase",
                    is_folder=True,
                    children=[
                        Link(
                            url="/sales/",
                            name="Customers",
                            icon="fa-solid fa-user",
                            is_internal=True,
                        )
                    ],
                )
            ]
        )
        request = self.factory.get("/")
        request.user = self.admin_user

        # 2. Render the tile and verify both icons.
        html = LinksTileRenderer.render(config, request)
        self.assertIn("fa-solid fa-briefcase", html)
        self.assertIn("fa-solid fa-user", html)

    def test_user_parameter_resolver_hides_model_object_without_view_permission(self):
        customer = self.CustomerModel.objects.create(
            first_name="Blocked",
            last_name="Customer",
            age=30,
            created_by=self.normal_user,
        )
        self.normal_user.visible_customers = self.CustomerModel.objects.filter(pk=customer.pk)
        resolver = UserParameterResolver(self.normal_user)

        rendered = resolver.resolve(
            "/customers/?customer={{ current_user.visible_customers.first() }}"
        )

        self.assertEqual(rendered, "/customers/?customer=")
        self.assertTrue(self.CustomerModel.objects.filter(pk=customer.pk).exists())

    def test_user_parameter_resolver_serializes_permitted_model_object_pk(self):
        pass
