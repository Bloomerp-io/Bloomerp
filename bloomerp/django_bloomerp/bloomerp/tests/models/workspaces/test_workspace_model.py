from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from bloomerp.models.definition import LayoutItem, LayoutRow, WorkspaceLayout
from bloomerp.models.project_management.initiative import Initiative, InitiativeStatus
from bloomerp.models.project_management.todo import Todo, TodoPriority, TodoStatus
from bloomerp.models.users.base_preference import BasePreference
from bloomerp.models.workspaces.tile import Tile
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.modules.definition import BloomerpModule, ModuleRegistry
from bloomerp.modules.todos_and_initiatives import TodosAndInitiatives
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.services.workspace_services import (
    create_or_update_default_tiles,
    render_tile_to_string,
    resolve_tile_type_from_config,
    select_workspace,
)
from bloomerp.tests.base import (
    BaseBloomerpTestCaseWithModels,
    BloomerpModelTestCase,
    ExpectedModelException,
    ModelScenario,
)
from bloomerp.tests.models.default_filters_scenarios import default_filter_scenarios
from bloomerp.workspaces.utils import has_access_to_workspace
from bloomerp.workspaces.text_tile.model import TextTileConfig
from bloomerp.workspaces.tiles import TileType


class TestWorkspaceModel(BloomerpModelTestCase, BaseBloomerpTestCaseWithModels):
    model = Workspace
    auto_create_customers = False

    def setUp(self):
        super().setUp()
        self.owner = get_user_model().objects.create_user(username='owner')
        self.other_user = get_user_model().objects.create_user(username='recipient')

    def get_test_scenarios(self) -> list[ModelScenario[Workspace]]:
        return [
            *default_filter_scenarios(self, lambda: {'user': self.owner, 'name': 'Workspace'}),
            ModelScenario(
                name='Sharing grants access and revocation removes it',
                description='UC: Share and revoke a workspace.\nExpected Result: References do not retain revoked access.',
                create_args=lambda: {'user': self.owner, 'name': 'Shared workspace'},
                create_validators=self.check_shared_access,
            ),
            ModelScenario(
                name="Workspace is a module-scoped base preference",
                description=(
                    "UC: Workspace selection is managed as a preference.\n"
                    "Expected Result: The preference scope is the module identifier."
                ),
                create_operation=lambda: Workspace,
                create_validators=lambda model: (
                    issubclass(model, BasePreference)
                    and model.preference_scope_fields == ("module_id",)
                ),
            ),
            ModelScenario(
                name="Default workspace is selected for its user and module",
                description=(
                    "UC: A user opens a module without a workspace preference.\n"
                    "Expected Result: A selected workspace is created in that module scope."
                ),
                create_operation=lambda: Workspace.create_default_for_user(
                    self.admin_user, module_id="sales"
                ),
                create_validators=lambda workspace: (
                    workspace.user == self.admin_user
                    and workspace.module_id == "sales"
                    and workspace.selected
                ),
            ),
            ModelScenario(
                name="Default tile synchronization updates by native ID",
                description=(
                    "UC: A module's declared tile changes.\n"
                    "Expected Result: Synchronization updates one auto-generated tile instead of duplicating it."
                ),
                create_operation=self.synchronize_default_tile,
                create_validators=self.default_tile_was_updated,
            ),
            ModelScenario(
                name="Every configured module workspace is materialized",
                description=(
                    "UC: A module declares multiple workspace layouts.\n"
                    "Expected Result: All are created, the default is selected, and native tile IDs resolve."
                ),
                create_operation=self.materialize_planning_workspaces,
                create_validators=self.planning_workspaces_are_materialized,
            ),
            ModelScenario(
                name="Todos dashboard materializes and renders every declared tile",
                description=(
                    "UC: A user opens the real Todos & Initiatives dashboard.\n"
                    "Expected Result: Its workspace, quick links, analytics, and all ten tiles are usable."
                ),
                create_operation=self.materialize_todos_dashboard,
                create_validators=self.todos_dashboard_is_complete,
            ),
            ModelScenario(
                name="Tile type resolves from registered configuration model",
                description=(
                    "UC: Workspace synchronization receives a typed tile configuration.\n"
                    "Expected Result: It resolves to the registered persisted tile type."
                ),
                create_operation=lambda: resolve_tile_type_from_config(TextTileConfig(id="notes")),
                create_validators=lambda tile_type: tile_type == TileType.TEXT_TILE.name,
            ),
            ModelScenario(
                name="Shared initial workspace creates selected live reference",
                description=(
                    "UC: A shared workspace is marked as the recipient's initial default.\n"
                    "Expected Result: Preference resolution returns it and creates a selected reference."
                ),
                create_operation=self.resolve_shared_initial_workspace,
                create_validators=self.shared_initial_reference_is_selected,
            ),
            ModelScenario(
                name="Workspace selection is independent per module",
                description=(
                    "UC: A user selects workspaces in two modules.\n"
                    "Expected Result: Both module-scoped selections remain selected."
                ),
                create_operation=self.create_two_module_selections,
                create_validators=lambda workspaces: all(workspace.selected for workspace in workspaces),
            ),
            ModelScenario(
                name="None module scope selects only a general workspace",
                description=(
                    "UC: Preference resolution receives the serialized None module scope.\n"
                    "Expected Result: A selected general workspace is created without unselecting module workspaces."
                ),
                create_operation=self.resolve_general_workspace,
                create_validators=self.general_and_module_workspaces_are_selected,
            ),
            ModelScenario(
                name="Database rejects multiple selected general workspaces",
                description=(
                    "UC: Two general workspaces are selected for one user.\n"
                    "Expected Result: The database uniqueness constraint rejects the second selection."
                ),
                create_operation=self.select_second_general_workspace,
                expected_exceptions=[
                    ExpectedModelException(phase="create", exception=IntegrityError)
                ],
            ),
            ModelScenario(
                name="Selecting shared workspace creates selected live reference",
                description=(
                    "UC: A user selects a workspace shared by someone else.\n"
                    "Expected Result: Their old selection is cleared and a selected live reference is created."
                ),
                create_operation=self.select_shared_workspace,
                create_validators=self.shared_workspace_selection_is_live,
            ),
            ModelScenario(
                name="Workspace returns tiles in layout order",
                description=(
                    "UC: A workspace layout orders tiles across rows.\n"
                    "Expected Result: get_tiles follows that exact layout order."
                ),
                create_operation=self.create_ordered_workspace,
                create_validators=self.tiles_follow_layout_order,
            ),
            ModelScenario(
                name="Workspace ignores stale and invalid tile IDs",
                description=(
                    "UC: A saved layout contains malformed and deleted tile IDs.\n"
                    "Expected Result: get_tiles returns only valid persisted tiles."
                ),
                create_operation=self.create_workspace_with_stale_tiles,
                create_validators=lambda workspace: list(workspace.get_tiles()) == [self.valid_tile],
            ),
        ]

    def check_shared_access(self, workspace):
        self.assertTrue(has_access_to_workspace(workspace, self.owner))
        self.assertFalse(has_access_to_workspace(workspace, self.other_user))
        workspace.shared_with_users.add(self.other_user)
        reference = Workspace.objects.create(user=self.other_user, source_object=workspace)
        self.assertTrue(has_access_to_workspace(workspace, self.other_user))
        self.assertTrue(has_access_to_workspace(reference, self.other_user))
        workspace.shared_with_users.clear()
        self.assertFalse(has_access_to_workspace(workspace, self.other_user))
        self.assertFalse(has_access_to_workspace(reference, self.other_user))
        return True

    def create_tile(self, name):
        return Tile.objects.create(
            name=name,
            description="",
            type=TileType.TEXT_TILE.name,
            schema={},
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )

    @staticmethod
    def planning_module():
        class PlanningModule(BloomerpModule):
            id = "planning"
            name = "Planning"
            tiles = [
                TextTileConfig(
                    id="planning:notes",
                    name="Planning notes",
                    markdown="Initial",
                )
            ]

        return PlanningModule

    def synchronize_default_tile(self):
        registry = ModuleRegistry()
        registry.register(self.planning_module().to_config())
        first = create_or_update_default_tiles(registry)["planning:notes"]
        self.initial_tile_pk = first.pk
        registry.get("planning").tiles[0].name = "Updated planning notes"
        registry.get("planning").tiles[0].markdown = "Updated"
        return create_or_update_default_tiles(registry)["planning:notes"]

    def default_tile_was_updated(self, tile):
        return (
            tile.pk == self.initial_tile_pk
            and tile.auto_generated
            and tile.type == TileType.TEXT_TILE.name
            and tile.schema["id"] == "planning:notes"
            and tile.name == "Updated planning notes"
            and tile.schema["markdown"] == "Updated"
            and Tile.get_default_tiles().filter(schema__id="planning:notes").count() == 1
            and Tile.get_tiles_by_native_ids(["planning:notes"]) == {"planning:notes": tile}
        )

    def materialize_planning_workspaces(self):
        PlanningModule = self.planning_module()
        PlanningModule.workspaces = [
            WorkspaceLayout(
                name="My planning",
                rows=[LayoutRow(columns=2, items=[LayoutItem(id="planning:notes", colspan=2)])],
            ),
            WorkspaceLayout(name="Planning overview", is_default=False, rows=[]),
        ]
        self.planning_registry = ModuleRegistry()
        self.planning_registry.register(PlanningModule.to_config())
        with patch("bloomerp.models.workspaces.workspace.module_registry", self.planning_registry):
            return Workspace.create_default_for_user(self.admin_user, module_id="planning")

    def planning_workspaces_are_materialized(self, selected):
        workspaces = list(
            Workspace.objects.filter(user=self.admin_user, module_id="planning").order_by("name")
        )
        tile = Tile.get_tile_by_native_id("planning:notes")
        return (
            len(workspaces) == 2
            and selected.name == "My planning"
            and selected.selected
            and not Workspace.objects.get(name="Planning overview").selected
            and selected.layout_obj.rows[0].items[0].id == str(tile.pk)
            and self.planning_registry.get("planning").workspaces[0].rows[0].items[0].id
            == "planning:notes"
        )

    def materialize_todos_dashboard(self):
        self.todos_registry = ModuleRegistry()
        self.todos_registry.register(TodosAndInitiatives.to_config())
        self.todos_registry._module_models["todos_and_initiatives"] = {
            Todo._meta.label_lower: Todo,
            Initiative._meta.label_lower: Initiative,
        }
        self.todos_registry.validate_workspace_tile_references()
        with patch("bloomerp.models.workspaces.workspace.module_registry", self.todos_registry):
            return Workspace.create_default_for_user(
                self.admin_user,
                module_id="todos_and_initiatives",
            )

    def todos_dashboard_is_complete(self, workspace):
        generated = {tile.schema["id"]: tile for tile in Tile.get_default_tiles()}
        materialized_ids = [
            str(item.id) for row in workspace.layout_obj.rows for item in row.items
        ]
        todo_links = {
            link["name"]: link["url"] for link in generated["todos:quick_links"].schema["links"]
        }
        links_are_valid = (
            todo_links["View all todos"] == reverse("todos_model")
            and todo_links["Create a todo"] == reverse("todos_add")
            and [
                link["url"] for link in generated["initiatives:quick_links"].schema["links"]
            ]
            == [reverse("initiatives_model"), reverse("initiatives_add")]
        )
        Todo.objects.create(
            title="Ship dashboard",
            status=TodoStatus.COMPLETED,
            priority=TodoPriority.HIGH,
            assigned_to=self.admin_user,
            datetime_created=timezone.now() - timedelta(days=2),
        )
        Todo.objects.create(
            title="Review backlog",
            status=TodoStatus.BACKLOG,
            priority=TodoPriority.URGENT,
            assigned_to=self.admin_user,
        )
        Initiative.objects.create(
            name="Dashboard rollout",
            status=InitiativeStatus.IN_PROGRESS,
            owner=self.admin_user,
        )
        request = RequestFactory().get("/")
        request.user = self.admin_user
        renders = all(render_tile_to_string(tile, request).strip() for tile in generated.values())
        return (
            workspace.name == "Todos & Initiatives overview"
            and workspace.selected
            and len(workspace.layout_obj.rows) == 4
            and len(generated) == 10
            and len(materialized_ids) == 10
            and set(materialized_ids) == {str(tile.pk) for tile in generated.values()}
            and links_are_valid
            and renders
        )

    def resolve_shared_initial_workspace(self):
        self.shared_initial = Workspace.objects.create(
            user=self.normal_user,
            module_id="sales",
            name="Shared sales workspace",
            initial_default=True,
            layout={"rows": [{"title": "Shared", "columns": 4, "items": []}]},
        )
        self.shared_initial.shared_with_users.add(self.admin_user)
        return PreferenceManager(self.admin_user).get_or_create_selected(
            Workspace, {"module_id": "sales"}
        )

    def shared_initial_reference_is_selected(self, result):
        reference = Workspace.objects.get(
            user=self.admin_user,
            source_object=self.shared_initial,
        )
        return result == self.shared_initial and reference.selected and reference.module_id == "sales"

    def create_two_module_selections(self):
        return [
            Workspace.objects.create(
                user=self.admin_user, module_id="sales", name="Sales", selected=True
            ),
            Workspace.objects.create(
                user=self.admin_user, module_id="finance", name="Finance", selected=True
            ),
        ]

    def resolve_general_workspace(self):
        self.module_workspace = Workspace.objects.create(
            user=self.admin_user,
            module_id="sales",
            name="Sales",
            selected=True,
        )
        return PreferenceManager(self.admin_user).get_or_create_selected(
            Workspace, {"module_id": "None"}
        )

    def general_and_module_workspaces_are_selected(self, general):
        self.module_workspace.refresh_from_db()
        return general.module_id is None and general.selected and self.module_workspace.selected

    def select_second_general_workspace(self):
        Workspace.objects.create(
            user=self.admin_user,
            module_id=None,
            name="Primary general workspace",
            selected=True,
        )
        secondary = Workspace.objects.create(
            user=self.admin_user,
            module_id=None,
            name="Secondary general workspace",
            selected=False,
        )
        Workspace.objects.filter(pk=secondary.pk).update(selected=True)
        return secondary

    def select_shared_workspace(self):
        self.current_workspace = Workspace.objects.create(
            user=self.admin_user,
            module_id="sales",
            name="Current",
            selected=True,
        )
        self.shared_workspace = Workspace.objects.create(
            user=self.normal_user,
            module_id="sales",
            name="Shared",
        )
        self.shared_workspace.shared_with_users.add(self.admin_user)
        return select_workspace(self.shared_workspace, self.admin_user)

    def shared_workspace_selection_is_live(self, effective):
        self.current_workspace.refresh_from_db()
        reference = Workspace.objects.get(
            user=self.admin_user,
            source_object=self.shared_workspace,
        )
        return effective == self.shared_workspace and not self.current_workspace.selected and reference.selected

    def create_ordered_workspace(self):
        first = self.create_tile("First")
        second = self.create_tile("Second")
        third = self.create_tile("Third")
        self.expected_tile_ids = [second.pk, first.pk, third.pk]
        return Workspace.objects.create(
            user=self.admin_user,
            name="Workspace",
            layout={
                "rows": [
                    {"columns": 4, "items": [{"id": str(second.pk)}, {"id": str(first.pk)}]},
                    {"columns": 4, "items": [{"id": str(third.pk)}]},
                ]
            },
        )

    def tiles_follow_layout_order(self, workspace):
        return list(workspace.get_tiles().values_list("pk", flat=True)) == self.expected_tile_ids

    def create_workspace_with_stale_tiles(self):
        self.valid_tile = self.create_tile("Only valid tile")
        return Workspace.objects.create(
            user=self.admin_user,
            name="Workspace",
            layout={
                "rows": [
                    {
                        "columns": 4,
                        "items": [
                            {"id": "not-a-tile"},
                            {"id": str(self.valid_tile.pk)},
                            {"id": "999999"},
                        ],
                    }
                ]
            },
        )
