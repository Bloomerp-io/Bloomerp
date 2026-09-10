from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase, TransactionTestCase
from django.urls import reverse
from pydantic import ValidationError

from bloomerp.tests.utils.dynamic_models import create_test_models
from django.db import models
from bloomerp.modules.definition import (
    BloomerpModule,
    ModuleRegistry,
    module_registry,
)
from bloomerp.models.definition import (
    BloomerpModelConfig,
    LayoutItem,
    LayoutRow,
    WorkspaceLayout,
)
from bloomerp.modules.users import UsersModule
from bloomerp.modules.automation import AutomationModule
from bloomerp.modules.todos_and_initiatives import TodosAndInitiatives
from bloomerp.models.automation.workflow import Workflow
from bloomerp.models.automation.workflow_run import WorkflowRun, WorkflowRunStatus
from bloomerp.models.automation.workflow_run_step import (
    WorkflowRunStep,
    WorkflowRunStepStatus,
)
from bloomerp.models.project_management.initiative import Initiative
from bloomerp.models.project_management.todo import Todo
from bloomerp.permissions.compilers.sql_permission_compiler import get_physical_tables
from bloomerp.services.sql_services import SqlExecutor
from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig
from bloomerp.workspaces.links_tile.model import Link, LinkTileConfig
from bloomerp.workspaces.text_tile.model import TextTileConfig


class AutomationDashboardQueryTests(TransactionTestCase):
    def test_success_and_attention_metrics_use_run_level_status(self):
        workflow = Workflow.objects.create(name="Test workflow")
        statuses = [
            (WorkflowRunStatus.SUCCEEDED, WorkflowRunStepStatus.COMPLETED),
            (WorkflowRunStatus.FAILED, WorkflowRunStepStatus.FAILED),
            (WorkflowRunStatus.PAUSED, WorkflowRunStepStatus.PAUSED),
            (WorkflowRunStatus.CANCELLED, WorkflowRunStepStatus.CANCELLED),
        ]
        for sequence, (run_status, step_status) in enumerate(statuses, start=1):
            run = WorkflowRun.objects.create(
                workflow=workflow,
                status=run_status,
            )
            WorkflowRunStep.objects.create(
                workflow_run=run,
                sequence=sequence,
                action_id=f"action-{sequence}",
                status=step_status,
            )

        tiles = {
            tile.id: tile
            for tile in WorkflowRun.bloomerp_config.tiles
        }
        success_result = SqlExecutor().execute_query(
            tiles["workflow_run:success_rate"].query,
            paginate=False,
        ).to_dataframe()
        attention_result = SqlExecutor().execute_query(
            tiles["workflow_run:runs_pending_action"].query,
            paginate=False,
        ).to_dataframe()

        self.assertAlmostEqual(success_result.iloc[0]["success_rate"], 1 / 3)
        self.assertEqual(attention_result.iloc[0]["attention_count"], 2)


class ModuleWorkspaceDefinitionTests(SimpleTestCase):
    def test_users_dashboard_provides_simple_management_shortcuts(self):
        registry = ModuleRegistry()
        registry.register(UsersModule.to_config())

        registry.validate_workspace_tile_references()

        module = registry.get("users")
        workspace = module.workspaces[0]
        workspace_tile_ids = [
            str(item.id)
            for row in workspace.rows
            for item in row.items
        ]
        resolved_tiles = {
            tile_id: registry.get_tile_for_module("users", tile_id)
            for tile_id in workspace_tile_ids
        }

        self.assertEqual(workspace.name, "Users & Permissions overview")
        self.assertTrue(workspace.is_default)
        self.assertEqual([row.title for row in workspace.rows], ["Quick access"])
        self.assertEqual(
            workspace_tile_ids,
            [
                "users:user-management",
                "users:permission-management",
            ],
        )
        self.assertTrue(all(resolved_tiles.values()))
        self.assertEqual(
            [
                link.url_name
                for link in resolved_tiles["users:user-management"].links
            ],
            ["users_model", "users_add"],
        )
        self.assertEqual(
            [
                link.url_name
                for link in resolved_tiles["users:permission-management"].links
            ],
            ["groups_model", "access_control_policies_model"],
        )

    def test_automation_dashboard_resolves_operational_tiles_and_uses_safe_queries(self):
        registry = ModuleRegistry()
        registry.register(AutomationModule.to_config())
        registry._module_models["automation"] = {
            Workflow._meta.label_lower: Workflow,
            WorkflowRun._meta.label_lower: WorkflowRun,
        }

        registry.validate_workspace_tile_references()

        module = registry.get("automation")
        workspace = module.workspaces[0]
        workspace_tile_ids = [
            str(item.id)
            for row in workspace.rows
            for item in row.items
        ]
        resolved_tiles = {
            tile_id: registry.get_tile_for_module("automation", tile_id)
            for tile_id in workspace_tile_ids
        }

        self.assertEqual(
            [row.title for row in workspace.rows],
            [
                "At a glance",
                "Quick Access",
                "Operational health",
                "Attention required",
                "Performance and usage",
                "Workflow hygiene",
            ],
        )
        self.assertEqual(len(workspace_tile_ids), 12)
        self.assertEqual(len(workspace_tile_ids), len(set(workspace_tile_ids)))
        self.assertTrue(all(resolved_tiles.values()))
        self.assertEqual(
            [
                link.url_name
                for link in resolved_tiles["automation:quick-access"].links
            ],
            ["workflows_model", "workflows_add"],
        )
        self.assertEqual(
            [
                link.url_name
                for link in resolved_tiles["automation:monitoring-links"].links
            ],
            ["workflow_runs_model"],
        )

        for tile in resolved_tiles.values():
            if not isinstance(tile, AnalyticsTileConfig):
                continue
            self.assertTrue(SqlExecutor().is_safe(tile.query))
            self.assertTrue(get_physical_tables(tile.query, dialect="postgres"))

    def test_todos_dashboard_resolves_all_tiles_and_uses_safe_queries(self):
        """The real Todo dashboard combines module and model-owned tiles."""
        registry = ModuleRegistry()
        registry.register(TodosAndInitiatives.to_config())
        registry._module_models["todos_and_initiatives"] = {
            Todo._meta.label_lower: Todo,
            Initiative._meta.label_lower: Initiative,
        }

        registry.validate_workspace_tile_references()

        module = registry.get("todos_and_initiatives")
        workspace = module.workspaces[0]
        workspace_tile_ids = [
            str(item.id)
            for row in workspace.rows
            for item in row.items
        ]
        resolved_tiles = {
            tile_id: registry.get_tile_for_module(
                "todos_and_initiatives",
                tile_id,
            )
            for tile_id in workspace_tile_ids
        }

        self.assertEqual(
            [row.title for row in workspace.rows],
            [
                "At a glance",
                "Quick access",
                "Work overview",
                "Priority and delivery",
            ],
        )
        self.assertEqual(len(workspace_tile_ids), 10)
        self.assertEqual(len(workspace_tile_ids), len(set(workspace_tile_ids)))
        self.assertTrue(all(resolved_tiles.values()))
        self.assertIsInstance(resolved_tiles["todos:quick_links"], LinkTileConfig)
        self.assertEqual(
            {
                link.name: link.url_name
                for link in resolved_tiles["todos:quick_links"].links
                if link.url_name
            },
            {
                "View all todos": "todos_model",
                "Create a todo": "todos_add",
            },
        )
        self.assertEqual(
            [link.url_name for link in resolved_tiles["initiatives:quick_links"].links],
            ["initiatives_model", "initiatives_add"],
        )
        self.assertIsInstance(
            resolved_tiles["todos:number_of_todos"],
            AnalyticsTileConfig,
        )
        self.assertIsInstance(
            resolved_tiles["initiatives:status_distribution"],
            AnalyticsTileConfig,
        )

        for tile in resolved_tiles.values():
            if not isinstance(tile, AnalyticsTileConfig):
                continue
            self.assertTrue(SqlExecutor().is_safe(tile.query))
            self.assertTrue(get_physical_tables(tile.query, dialect="postgres"))

    def test_module_accepts_tiles_and_multiple_workspace_definitions(self):
        """
        Use case: A module declares its own tile and multiple default workspaces.
        Expected result: Concrete tile payloads and workspace metadata are preserved.
        """
        # 1. Define a module-owned links tile and two workspace layouts.
        class PlanningModule(BloomerpModule):
            id = "planning"
            name = "Planning"
            tiles = [
                LinkTileConfig(
                    id="navigation",
                    name="Planning navigation",
                    links=[Link(name="Todos", url="/todos/", is_internal=True)],
                )
            ]
            workspaces = [
                WorkspaceLayout(
                    name="My work",
                    rows=[
                        LayoutRow(
                            columns=2,
                            items=[LayoutItem(id="navigation")],
                        )
                    ],
                ),
                WorkspaceLayout(
                    name="Overview",
                    is_default=False,
                    rows=[],
                ),
            ]

        # 2. Convert the authoring class to its validated module config.
        config = PlanningModule.to_config()

        # 3. Verify polymorphic tiles and workspace defaults remain intact.
        self.assertIsInstance(config.tiles[0], LinkTileConfig)
        self.assertEqual(config.tiles[0].links[0].name, "Todos")
        self.assertEqual([workspace.name for workspace in config.workspaces], ["My work", "Overview"])
        self.assertTrue(config.workspaces[0].is_default)
        self.assertFalse(config.workspaces[1].is_default)
        self.assertEqual(
            config.model_dump()["tiles"][0]["links"][0]["url"],
            "/todos/",
        )

    def test_module_requires_exactly_one_default_workspace(self):
        """
        Use case: A module declares multiple workspace layouts.
        Expected result: Configuration rejects ambiguous default selection.
        """
        # 1. Define two workspaces that both use the BaseLayout default flag.
        class AmbiguousModule(BloomerpModule):
            id = "ambiguous"
            name = "Ambiguous"
            workspaces = [
                WorkspaceLayout(name="First"),
                WorkspaceLayout(name="Second"),
            ]

        # 2. Verify conversion rejects more than one default workspace.
        with self.assertRaisesRegex(ValidationError, "exactly one default workspace"):
            AmbiguousModule.to_config()

    def test_registry_resolves_module_and_model_tiles_for_workspaces(self):
        """
        Use case: A module workspace references one module tile and one model tile by ID.
        Expected result: Both IDs resolve through the module registry.
        """
        # 1. Create a module with its own tile and workspace references.
        class PlanningModule(BloomerpModule):
            id = "planning"
            name = "Planning"
            tiles = [LinkTileConfig(id="navigation", links=[])]
            workspaces = [
                WorkspaceLayout(
                    name="Default",
                    rows=[
                        LayoutRow(
                            columns=2,
                            items=[
                                LayoutItem(id="navigation"),
                                LayoutItem(id="todo_summary"),
                            ],
                        )
                    ],
                )
            ]

        # 2. Register a model-owned tile under the same module.
        class TodoModel:
            bloomerp_config = BloomerpModelConfig(
                module="planning",
                tiles=[TextTileConfig(id="todo_summary", markdown="Todos")],
            )

        registry = ModuleRegistry()
        registry.register(PlanningModule.to_config())
        registry._module_models["planning"] = {"example.todo": TodoModel}

        # 3. Validate and resolve both sources by their declarative IDs.
        registry.validate_workspace_tile_references()
        self.assertIsInstance(
            registry.get_tile_for_module("planning", "navigation"),
            LinkTileConfig,
        )
        self.assertIsInstance(
            registry.get_tile_for_module("planning", "todo_summary"),
            TextTileConfig,
        )

    def test_registry_rejects_unknown_workspace_tile_ids(self):
        """
        Use case: A workspace references a tile absent from its module and models.
        Expected result: Registry validation reports the unresolved tile ID.
        """
        # 1. Register a workspace containing an unknown tile reference.
        class InvalidModule(BloomerpModule):
            id = "invalid"
            name = "Invalid"
            workspaces = [
                WorkspaceLayout(
                    rows=[
                        LayoutRow(
                            columns=1,
                            items=[LayoutItem(id="missing")],
                        )
                    ]
                )
            ]

        registry = ModuleRegistry()
        registry.register(InvalidModule.to_config())

        # 2. Verify the unresolved reference is rejected.
        with self.assertRaisesRegex(ValueError, "unknown tile id 'missing'"):
            registry.validate_workspace_tile_references()

class TestModules(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.CustomerModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "Customer": {
                    "first_name": models.CharField(max_length=100),
                    "last_name": models.CharField(max_length=100),
                }
            },
            use_bloomerp_base=True,
            bloomerp_config=None, # Should be added to 'misc' module
        )["Customer"]

        cls.OrderModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "Order": {
                    "order_number": models.CharField(max_length=100),
                    "customer": models.ForeignKey(
                        cls.CustomerModel, 
                        on_delete=models.CASCADE,
                        related_name="orders"
                    ),
                }
            },
            use_bloomerp_base=True,
            bloomerp_config=BloomerpModelConfig(module="data"), # Should be added to 'data' module
        )["Order"]
        
        module_registry.refresh()
         
    def test_model_automatically_assigned_to_misc_module(self):
        """Tests whether a model without module specification is assigned to 'misc' module."""
        models = module_registry.get_models_for_module("misc")
        
        # Check if CustomerModel is in misc module
        self.assertIn(
            self.CustomerModel, 
            models, 
        )
        
    def test_model_assigned_to_specified_module(self):
        """Tests whether a model with module specification is assigned to the correct module."""
        models = module_registry.get_models_for_module("data")
        
        # Check if OrderModel is in data module
        self.assertIn(
            self.OrderModel, 
            models, 
        )
    
    def test_get_module_for_model(self):
        """Tests whether get_module_for_model returns the correct module for a given model."""
        customer_module = module_registry.get_module_for_model(self.CustomerModel)
        order_module = module_registry.get_module_for_model(self.OrderModel)
        
        # Check if CustomerModel is in misc module
        self.assertIsNotNone(customer_module)
        self.assertEqual(customer_module.id, "misc")
        
        # Check if OrderModel is in data module
        self.assertIsNotNone(order_module)
        self.assertEqual(order_module.id, "data")

    def test_module_subclass_allows_plain_class_attributes(self):
        """Module subclasses should not need repeated type annotations."""

        class PlainModule(BloomerpModule):
            id = "plain"
            name = "Plain"
            code = "plain"

        module = PlainModule.to_config()

        self.assertEqual(module.id, "plain")
        self.assertEqual(module.name, "Plain")
        self.assertEqual(module.code, "plain")

    def test_declared_route_path_survives_hierarchy_rebuild(self):
        class TodosModule(BloomerpModule):
            id = "todos_and_initiatives"
            name = "Todos & Initiatives"
            code = "todos"
            route_path = "todos-and-initiatives"

        registry = ModuleRegistry()
        registry.register(TodosModule.to_config())
        registry._rebuild_hierarchy_metadata()

        module = registry.get("todos_and_initiatives")

        self.assertEqual(module.route_path, "todos-and-initiatives")

    def test_descendant_route_uses_declared_parent_path(self):
        class OperationsModule(BloomerpModule):
            id = "operations"
            name = "Operations"
            route_path = "business-operations"

        class PlanningModule(BloomerpModule):
            id = "planning"
            name = "Planning"
            parent_module_id = "operations"

        registry = ModuleRegistry()
        registry.register(OperationsModule.to_config())
        registry.register(PlanningModule.to_config())
        registry._rebuild_hierarchy_metadata()

        self.assertEqual(
            registry.get("operations.planning").route_path,
            "business-operations/planning",
        )

    def test_home_module_link_uses_resolved_route_path(self):
        html = render_to_string(
            "views/workspaces/bloomerp_home_view.html",
            {
                "modules": [
                    SimpleNamespace(
                        id="todos_and_initiatives",
                        route_path="todos-and-initiatives",
                        name="Todos & Initiatives",
                        description="Manage todos and initiatives.",
                        icon="fa-tasks",
                    )
                ]
            },
        )

        self.assertIn('hx-get="/todos-and-initiatives/"', html)
        self.assertNotIn('hx-get="/todos_and_initiatives/"', html)

    def test_generated_model_routes_use_declared_module_path(self):
        self.assertEqual(
            reverse("todos_model"),
            "/todos-and-initiatives/todos/",
        )
        self.assertEqual(
            reverse("initiatives_model"),
            "/todos-and-initiatives/initiatives/",
        )

    def test_bloomerp_model_config_accepts_module_class(self):
        """Model config can reference a module authoring class directly."""
        config = BloomerpModelConfig(module=UsersModule)

        self.assertEqual(config.module, "users")
