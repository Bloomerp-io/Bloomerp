"""Exercise the historical label data copy and real retirement schema together."""

from importlib import import_module
from typing import Any
from uuid import uuid4

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.loader import MigrationLoader
from django.test import override_settings

from bloomerp.models.application_field import ApplicationField
from bloomerp.models.communication.label import Label
from bloomerp.models.communication.object_label import ObjectLabel
from bloomerp.models.project_management.initiative import Initiative
from bloomerp.models.project_management.todo import Todo
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels


class TestTodoLabelMigration(BaseBloomerpTestCaseWithModels):
    """Use isolated test-database legacy tables without changing deployed records."""

    auto_create_customers = False

    def setUp(self) -> None:
        """Reconstruct the three retired tables from the preceding migration state."""
        super().setUp()
        with override_settings(MIGRATION_MODULES={}):
            self.before = MigrationLoader(None).project_state(
                ("bloomerp", "0092_conversation_activity"),
            )
        self.legacy_label = self.before.apps.get_model("bloomerp", "TodoLabel")
        self.legacy_tables = [self.legacy_label]
        for name in ("Todo", "Initiative"):
            model = self.before.apps.get_model("bloomerp", name)
            self.legacy_tables.append(
                model._meta.get_field("labels").remote_field.through
            )
        with connection.schema_editor() as editor:
            for model in self.legacy_tables:
                editor.create_model(model)
        self.addCleanup(self.remove_legacy_tables)
        self.migration_module = import_module(
            "bloomerp.migrations.0093_migrate_todo_labels"
        )

    def remove_legacy_tables(self) -> None:
        """Drop historical tables left by data-only tests before database teardown."""
        tables = connection.introspection.table_names()
        with connection.schema_editor() as editor:
            for model in reversed(self.legacy_tables):
                if model._meta.db_table in tables:
                    editor.delete_model(model)

    def attach_legacy(self, parent: Todo | Initiative, label: Any) -> None:
        """Create an assignment through the historical model's actual join table."""
        model = self.before.apps.get_model("bloomerp", type(parent).__name__)
        through = model._meta.get_field("labels").remote_field.through
        through.objects.create(
            **{f"{model._meta.model_name}_id": parent.pk, "todolabel_id": label.pk},
        )

    def test_copy_preserves_both_parent_types_and_retires_schema(self) -> None:
        """Coalesce normalized names, retain unrelated assignments, and drop only legacy tables."""
        shared_id = uuid4()
        todo = Todo.objects.create(id=shared_id, title="Todo label migration")
        second_todo = Todo.objects.create(title="Second todo")
        initiative = Initiative.objects.create(
            id=shared_id, name="Initiative label migration"
        )
        existing = Label.objects.create(
            name="Backend", color="#123456", created_by=self.admin_user
        )
        existing_attachment = ObjectLabel.objects.create(
            label=existing,
            content_type=ContentType.objects.get_for_model(todo),
            object_id=str(todo.pk),
        )
        unrelated = Label.objects.create(name="Unrelated")
        unrelated_attachment = ObjectLabel.objects.create(
            label=unrelated,
            content_type=ContentType.objects.get_for_model(second_todo),
            object_id=str(second_todo.pk),
        )
        first = self.legacy_label.objects.create(name=" backend ", color="#ffffff")
        duplicate = self.legacy_label.objects.create(name="BACKEND", color="#000000")
        new = self.legacy_label.objects.create(
            name="  Frontend  ",
            color="#fedcba",
            created_by_id=self.admin_user.pk,
            updated_by_id=self.admin_user.pk,
        )
        unused = self.legacy_label.objects.create(name="Unused", color="#ffffff")
        legacy_metadata = []
        for model_name in ("todo", "initiative", "todolabel"):
            content_type, _ = ContentType.objects.get_or_create(
                app_label="bloomerp",
                model=model_name,
            )
            legacy_metadata.append(
                ApplicationField.objects.create(
                    content_type=content_type,
                    field="name" if model_name == "todolabel" else "labels",
                    field_type="CharField"
                    if model_name == "todolabel"
                    else "ManyToManyField",
                ).pk
            )
        surviving_field = ApplicationField.get_by_field(Todo, "title")
        for parent, label in (
            (todo, first),
            (todo, duplicate),
            (initiative, first),
            (initiative, duplicate),
            (initiative, new),
            (second_todo, new),
        ):
            self.attach_legacy(parent, label)

        migration = self.migration_module.Migration(
            "0093_migrate_todo_labels", "bloomerp"
        )
        with connection.schema_editor() as editor:
            after = migration.apply(self.before, editor)

        existing.refresh_from_db()
        self.assertEqual(
            (existing.name, existing.color, existing.created_by_id),
            ("Backend", "#123456", self.admin_user.pk),
        )
        frontend = Label.objects.get(name="Frontend")
        self.assertEqual(frontend.color, "#64748b")
        self.assertEqual(
            (frontend.created_by_id, frontend.updated_by_id),
            (self.admin_user.pk, self.admin_user.pk),
        )
        self.assertTrue(Label.objects.filter(name=unused.name).exists())
        self.assertEqual(set(todo.object_labels), {existing})
        self.assertEqual(set(initiative.object_labels), {existing, frontend})
        self.assertEqual(set(second_todo.object_labels), {unrelated, frontend})
        self.assertTrue(ObjectLabel.objects.filter(pk=existing_attachment.pk).exists())
        self.assertTrue(ObjectLabel.objects.filter(pk=unrelated_attachment.pk).exists())
        self.assertEqual(ObjectLabel.objects.count(), 5)
        self.assertEqual(Label.objects.count(), 4)
        self.assertFalse(
            ApplicationField.objects.filter(pk__in=legacy_metadata).exists()
        )
        self.assertTrue(ApplicationField.objects.filter(pk=surviving_field.pk).exists())
        tables = connection.introspection.table_names()
        for model in self.legacy_tables:
            self.assertNotIn(model._meta.db_table, tables)
        self.assertNotIn(("bloomerp", "todolabel"), after.models)
        for model_name in ("todo", "initiative"):
            self.assertNotIn("labels", after.models[("bloomerp", model_name)].fields)
        with connection.schema_editor() as editor, self.assertRaises(IrreversibleError):
            migration.unapply(self.before, editor)
        self.assertEqual(tables, connection.introspection.table_names())
        self.assertEqual(ObjectLabel.objects.count(), 5)

    def test_copy_is_idempotent_and_preserves_blank_legacy_labels(self) -> None:
        """Keep malformed blank labels attached under a stable fallback across retries."""
        todo = Todo.objects.create(title="Blank label")
        legacy = self.legacy_label.objects.create(name=" \t ", color="#ffffff")
        self.attach_legacy(todo, legacy)
        for _ in range(2):
            self.migration_module.migrate_todo_labels(
                self.before.apps, connection.schema_editor()
            )
        label = Label.objects.get(name=f"Untitled todo label ({legacy.pk})")
        self.assertEqual(list(todo.object_labels), [label])
        self.assertEqual(Label.objects.count(), 1)
        self.assertEqual(ObjectLabel.objects.count(), 1)

    def test_empty_legacy_catalogue_can_be_retired(self) -> None:
        """Allow fresh installations with no old labels to run the real schema operations."""
        migration = self.migration_module.Migration(
            "0093_migrate_todo_labels", "bloomerp"
        )
        with connection.schema_editor() as editor:
            migration.apply(self.before, editor)
        self.assertEqual(Label.objects.count(), 0)
        self.assertEqual(ObjectLabel.objects.count(), 0)

    def create_saved_filter(
        self,
        model: type[Todo] | type[Initiative],
        groups: list[dict[str, Any]],
        name: str = "Saved labels",
    ) -> Any:
        """Store historical grouped filters without resolving retired runtime fields."""
        content_type = ContentType.objects.get_for_model(model)
        return self.before.apps.get_model("bloomerp", "SavedFilter").objects.create(
            name=name,
            scope="model",
            identifier=str(content_type.pk),
            filters=groups,
        )

    def test_direct_saved_filters_keep_connectors_and_map_uuid_values(self) -> None:
        """Translate equivalent membership presets for both models, including legacy list values."""
        first = self.legacy_label.objects.create(name="First", color="#ffffff")
        second = self.legacy_label.objects.create(name="Second", color="#ffffff")
        presets = []
        for model in (Todo, Initiative):
            parent = model.objects.create(
                **({"title": "Filtered"} if model is Todo else {"name": "Filtered"})
            )
            self.attach_legacy(parent, first)
            groups = [
                {
                    "connector": "OR",
                    "conditions": [
                        {
                            "field_path": "labels",
                            "lookup_id": "equals",
                            "value": [str(first.pk)],
                        },
                        {
                            "field_path": "status",
                            "lookup_id": "equals",
                            "value": "scoped",
                        },
                    ],
                },
                {
                    "connector": "AND",
                    "conditions": [
                        {
                            "field_path": "labels",
                            "lookup_id": "not_equals",
                            "value": str(second.pk),
                        },
                        {
                            "field_path": "labels",
                            "lookup_id": "values_in",
                            "value": [str(first.pk), str(first.pk)],
                        },
                    ],
                },
            ]
            presets.append(self.create_saved_filter(model, groups))
        self.migration_module.migrate_todo_labels(
            self.before.apps, connection.schema_editor()
        )
        mapped_first = Label.objects.get(name="First").pk
        mapped_second = Label.objects.get(name="Second").pk
        for preset in presets:
            preset.refresh_from_db()
            self.assertEqual(
                preset.filters,
                [
                    {
                        "connector": "OR",
                        "conditions": [
                            {
                                "field_path": "object_labels",
                                "lookup_id": "equals",
                                "value": mapped_first,
                            },
                            {
                                "field_path": "status",
                                "lookup_id": "equals",
                                "value": "scoped",
                            },
                        ],
                    },
                    {
                        "connector": "AND",
                        "conditions": [
                            {
                                "field_path": "object_labels",
                                "lookup_id": "not_equals",
                                "value": mapped_second,
                            },
                            {
                                "field_path": "object_labels",
                                "lookup_id": "values_in",
                                "value": [mapped_first],
                            },
                        ],
                    },
                ],
            )

    def test_unsupported_presets_abort_before_any_writes(self) -> None:
        """Leave legacy rows, approved presets, metadata, and target tables untouched on preflight failure."""
        from django.test.utils import CaptureQueriesContext

        legacy = self.legacy_label.objects.create(name="Protected", color="#ffffff")
        todo = Todo.objects.create(title="Retained")
        self.attach_legacy(todo, legacy)
        original = [
            {
                "connector": "AND",
                "conditions": [
                    {
                        "field_path": "labels",
                        "lookup_id": "equals",
                        "value": str(legacy.pk),
                    },
                ],
            }
        ]
        safe = self.create_saved_filter(Todo, original, name="A safe preset")
        for scope, path, lookup, value in (
            ("model", "labels__name", "equals", "Protected"),
            ("model", "initiative__labels", "equals", str(legacy.pk)),
            ("model", "labels", "is_null", True),
            ("model", "labels", "equals", str(uuid4())),
            ("model", "labels", "equals", [str(legacy.pk), str(legacy.pk)]),
        ):
            with self.subTest(scope=scope, path=path, lookup=lookup):
                blocked = self.create_saved_filter(
                    Todo,
                    [
                        {
                            "connector": "AND",
                            "conditions": [
                                {
                                    "field_path": path,
                                    "lookup_id": lookup,
                                    "value": value,
                                },
                            ],
                        }
                    ],
                    name="Z requires review",
                )
                type(blocked).objects.filter(pk=blocked.pk).update(scope=scope)
                with (
                    CaptureQueriesContext(connection) as queries,
                    self.assertRaisesRegex(RuntimeError, str(blocked.pk)),
                ):
                    self.migration_module.migrate_todo_labels(
                        self.before.apps, connection.schema_editor()
                    )
                mutations = [
                    query["sql"]
                    for query in queries
                    if query["sql"].lstrip().split(" ", 1)[0]
                    in {"INSERT", "UPDATE", "DELETE", "ALTER", "DROP"}
                ]
                self.assertEqual(mutations, [])
                self.assertEqual(Label.objects.count(), 0)
                self.assertEqual(ObjectLabel.objects.count(), 0)
                safe.refresh_from_db()
                self.assertEqual(safe.filters, original)
                self.assertTrue(self.legacy_label.objects.filter(pk=legacy.pk).exists())
                blocked.delete()

    def test_filter_coalescing_cannot_broaden_matching_parents(self) -> None:
        """Reject either positive or negative membership whose merged label adds another parent."""
        first = self.legacy_label.objects.create(name="Duplicate", color="#ffffff")
        duplicate = self.legacy_label.objects.create(
            name=" duplicate ", color="#000000"
        )
        self.attach_legacy(Todo.objects.create(title="First"), first)
        self.attach_legacy(Todo.objects.create(title="Second"), duplicate)
        for lookup in ("equals", "not_equals", "values_in"):
            with self.subTest(lookup=lookup):
                value = [str(first.pk)] if lookup == "values_in" else str(first.pk)
                preset = self.create_saved_filter(
                    Todo,
                    [
                        {
                            "connector": "AND",
                            "conditions": [
                                {
                                    "field_path": "labels",
                                    "lookup_id": lookup,
                                    "value": value,
                                },
                            ],
                        }
                    ],
                )
                with self.assertRaisesRegex(RuntimeError, "change matching records"):
                    self.migration_module.migrate_todo_labels(
                        self.before.apps, connection.schema_editor()
                    )
                self.assertEqual(Label.objects.count(), 0)
                preset.delete()

    def test_existing_shared_assignments_cannot_broaden_saved_filters(self) -> None:
        """Keep a reused general label from silently including an unrelated Todo in a preset."""
        legacy = self.legacy_label.objects.create(name="Shared", color="#ffffff")
        self.attach_legacy(Todo.objects.create(title="Legacy match"), legacy)
        general_only = Todo.objects.create(title="General label only")
        shared = Label.objects.create(name="Shared")
        ObjectLabel.objects.create(
            label=shared,
            content_type=ContentType.objects.get_for_model(Todo),
            object_id=str(general_only.pk),
        )
        self.create_saved_filter(
            Todo,
            [
                {
                    "connector": "AND",
                    "conditions": [
                        {
                            "field_path": "labels",
                            "lookup_id": "equals",
                            "value": str(legacy.pk),
                        },
                    ],
                }
            ],
        )
        with self.assertRaisesRegex(RuntimeError, "change matching records"):
            self.migration_module.migrate_todo_labels(
                self.before.apps, connection.schema_editor()
            )
        self.assertEqual(Label.objects.count(), 1)
        self.assertEqual(ObjectLabel.objects.count(), 1)

    def test_row_policy_references_require_manual_review(self) -> None:
        """Abort modern, nested, and legacy metadata-ID access rules without changing any grant."""
        content_type = ContentType.objects.get_for_model(Todo)
        retired = ApplicationField.objects.create(
            content_type=content_type, field="labels", field_type="ManyToManyField"
        )
        policy = self.before.apps.get_model("bloomerp", "RowPolicy").objects.create(
            content_type_id=content_type.pk
        )
        rule_model = self.before.apps.get_model("bloomerp", "RowPolicyRule")
        for condition in (
            {"field_path": "labels", "lookup_id": "equals", "value": str(uuid4())},
            {
                "field_path": "initiative__labels__name",
                "lookup_id": "equals",
                "value": "Confidential",
            },
            {
                "application_field_id": retired.pk,
                "operator": "exact",
                "value": str(uuid4()),
            },
            {
                "field": "initiative",
                "operator": "__initiative__labels__name__exact",
                "value": "Confidential",
            },
        ):
            with self.subTest(condition=condition):
                rule = rule_model.objects.create(
                    row_policy_id=policy.pk,
                    rule={"connector": "AND", "conditions": [condition]},
                )
                with self.assertRaisesRegex(RuntimeError, f"RowPolicyRule {rule.pk}"):
                    self.migration_module.migrate_todo_labels(
                        self.before.apps, connection.schema_editor()
                    )
                rule.refresh_from_db()
                self.assertEqual(
                    rule.rule, {"connector": "AND", "conditions": [condition]}
                )
                self.assertTrue(ApplicationField.objects.filter(pk=retired.pk).exists())
                rule.delete()

    def test_failure_after_copy_rolls_back_the_entire_migration(self) -> None:
        """Roll back new labels, attachments, and preset rewrites before any legacy table is lost."""
        from unittest.mock import patch

        legacy = self.legacy_label.objects.create(name="Rollback", color="#ffffff")
        todo = Todo.objects.create(title="Rollback parent")
        self.attach_legacy(todo, legacy)
        groups = [
            {
                "connector": "AND",
                "conditions": [
                    {
                        "field_path": "labels",
                        "lookup_id": "equals",
                        "value": str(legacy.pk),
                    },
                ],
            }
        ]
        preset = self.create_saved_filter(Todo, groups)
        migration = self.migration_module.Migration(
            "0093_migrate_todo_labels", "bloomerp"
        )
        with (
            patch.object(
                self.migration_module,
                "retire_label_application_fields",
                side_effect=RuntimeError("Injected after copy"),
            ),
            self.assertRaisesRegex(RuntimeError, "Injected after copy"),
            connection.schema_editor() as editor,
        ):
            migration.apply(self.before.clone(), editor)
        self.assertEqual(Label.objects.count(), 0)
        self.assertEqual(ObjectLabel.objects.count(), 0)
        preset.refresh_from_db()
        self.assertEqual(preset.filters, groups)
        self.assertTrue(self.legacy_label.objects.filter(pk=legacy.pk).exists())
        for model in self.legacy_tables:
            self.assertIn(model._meta.db_table, connection.introspection.table_names())

    def test_workspace_aliases_and_source_preferences_require_manual_review(
        self,
    ) -> None:
        """Find renamed shared labels through inherited workspaces without blocking analytics columns."""
        workspace_model = self.before.apps.get_model("bloomerp", "Workspace")
        tile_model = self.before.apps.get_model("bloomerp", "Tile")
        todo_type = ContentType.objects.get_for_model(Todo)
        tile = tile_model.objects.create(
            name="Todo board",
            type="DATAVIEW_TILE",
            schema={
                "content_type_id": todo_type.pk,
                "filter_shared_keys": {"labels": "project__category"},
            },
        )
        source = workspace_model.objects.create(
            user_id=self.admin_user.pk,
            name="Source",
            layout={
                "rows": [
                    {"columns": 1, "items": [{"id": str(tile.pk)}]},
                ]
            },
        )
        reference = workspace_model.objects.create(
            user_id=self.normal_user.pk, name="Reference", source_object_id=source.pk
        )
        filter_model = self.before.apps.get_model("bloomerp", "SavedFilter")
        for path in (
            "shared:project__category",
            "shared:project__category__name",
            f"tile_{tile.pk}:labels",
        ):
            with self.subTest(path=path):
                preset = filter_model.objects.create(
                    name="Workspace labels",
                    scope="workspace",
                    identifier=str(reference.pk),
                    filters=[
                        {
                            "connector": "AND",
                            "conditions": [
                                {
                                    "field_path": path,
                                    "lookup_id": "equals",
                                    "value": str(uuid4()),
                                }
                            ],
                        },
                    ],
                )
                with self.assertRaisesRegex(RuntimeError, str(preset.pk)):
                    self.migration_module.migrate_todo_labels(
                        self.before.apps, connection.schema_editor()
                    )
                self.assertEqual(Label.objects.count(), 0)
                preset.delete()
        tile.schema["filter_shared_keys"] = {
            "labels": "project",
            "title": "project__category",
        }
        tile.save()
        unrelated = filter_model.objects.create(
            name="Longer title alias",
            scope="workspace",
            identifier=str(reference.pk),
            filters=[
                {
                    "connector": "AND",
                    "conditions": [
                        {
                            "field_path": "shared:project__category",
                            "lookup_id": "equals",
                            "value": "A title",
                        }
                    ],
                }
            ],
        )
        self.migration_module.migrate_todo_labels(
            self.before.apps, connection.schema_editor()
        )
        unrelated.refresh_from_db()
        self.assertEqual(unrelated.filters[0]["conditions"][0]["value"], "A title")
        unrelated.delete()
        tile.type = "ANALYTICS_TILE"
        tile.schema = {"query": "SELECT 1 AS labels"}
        tile.save()
        preset = filter_model.objects.create(
            name="Unrelated result labels",
            scope="workspace",
            identifier=str(reference.pk),
            filters=[
                {
                    "connector": "AND",
                    "conditions": [
                        {
                            "field_path": "shared:labels",
                            "lookup_id": "equals",
                            "value": 1,
                        }
                    ],
                },
            ],
        )
        self.migration_module.migrate_todo_labels(
            self.before.apps, connection.schema_editor()
        )
        preset.refresh_from_db()
        self.assertEqual(
            preset.filters[0]["conditions"][0]["field_path"], "shared:labels"
        )

    def test_dataview_tile_initial_filters_require_manual_review(self) -> None:
        """Catch both saved shorthand and serialized JSON filters before dropping their relation."""
        import json

        tile_model = self.before.apps.get_model("bloomerp", "Tile")
        for query in (
            {"labels": str(uuid4())},
            {"labels_eq": str(uuid4())},
            {"initiative__labels__name__exact": "Confidential"},
            {
                "filter": json.dumps(
                    [
                        {
                            "connector": "AND",
                            "conditions": [
                                {
                                    "field_path": "labels",
                                    "lookup_id": "equals",
                                    "value": str(uuid4()),
                                },
                            ],
                        }
                    ]
                )
            },
        ):
            with self.subTest(query=query):
                tile = tile_model.objects.create(
                    name="Stored filter",
                    type="DATAVIEW_TILE",
                    schema={
                        "content_type_id": ContentType.objects.get_for_model(Todo).pk,
                        "initial_query_params": query,
                    },
                )
                with self.assertRaisesRegex(RuntimeError, f"Tile {tile.pk}"):
                    self.migration_module.migrate_todo_labels(
                        self.before.apps, connection.schema_editor()
                    )
                tile.refresh_from_db()
                self.assertEqual(tile.schema["initial_query_params"], query)
                self.assertEqual(Label.objects.count(), 0)
                tile.delete()

    def test_merge_migration_keeps_both_branch_operations(self) -> None:
        """Require one graph leaf containing both independent migrations without new operations."""
        with override_settings(MIGRATION_MODULES={}):
            loader = MigrationLoader(None)
        key = ("bloomerp", "0094_merge_list_view_mode_todo_labels")
        branches = {
            ("bloomerp", "0093_list_view_mode"),
            ("bloomerp", "0093_migrate_todo_labels"),
        }
        merge = loader.disk_migrations[key]
        self.assertEqual(set(merge.dependencies), branches)
        self.assertEqual(merge.operations, [])
        self.assertEqual(loader.detect_conflicts(), {})
        self.assertEqual(len(loader.graph.leaf_nodes("bloomerp")), 1)
        plan = loader.graph.forwards_plan(loader.graph.leaf_nodes("bloomerp")[0])
        self.assertIn(key, plan)
        for branch in branches:
            self.assertLess(plan.index(branch), plan.index(key))
        merged_state = loader.project_state(key)
        preference_fields = merged_state.models[
            ("bloomerp", "userlistviewpreference")
        ].fields
        self.assertIn("view_mode", preference_fields)
        self.assertNotIn("split_view_enabled", preference_fields)
        self.assertNotIn(("bloomerp", "todolabel"), merged_state.models)
        for model_name in ("todo", "initiative"):
            self.assertNotIn(
                "labels", merged_state.models[("bloomerp", model_name)].fields
            )

    def test_merge_preserves_data_when_upgrading_from_either_branch(self) -> None:
        """Apply each sibling first in isolation, retaining split preferences and both label joins."""
        from django.db import connections

        branches = ("0093_list_view_mode", "0093_migrate_todo_labels")
        for first in branches:
            with self.subTest(first=first):
                alias = "todo_label_merge"
                connections.databases[alias] = {
                    **connections.databases["default"],
                    "ENGINE": "django.db.backends.sqlite3",
                    "NAME": ":memory:",
                }
                isolated = connections[alias]
                isolated.connect()
                try:
                    state = self.before.clone()
                    with isolated.schema_editor() as editor:
                        for model in state.apps.get_models():
                            if model._meta.managed and not model._meta.proxy:
                                editor.create_model(model)
                    owner = (
                        state.apps.get_model(settings.AUTH_USER_MODEL)
                        .objects.using(alias)
                        .create(username="merge-owner")
                    )
                    content_types = state.apps.get_model(
                        "contenttypes", "ContentType"
                    ).objects.using(alias)
                    todo_type = content_types.create(app_label="bloomerp", model="todo")
                    initiative_type = content_types.create(
                        app_label="bloomerp", model="initiative"
                    )
                    preferences = state.apps.get_model(
                        "bloomerp", "UserListViewPreference"
                    ).objects.using(alias)
                    preferences.create(
                        user_id=owner.pk,
                        content_type_id=todo_type.pk,
                        name="Normal",
                        split_view_enabled=False,
                    )
                    preferences.create(
                        user_id=owner.pk,
                        content_type_id=todo_type.pk,
                        name="Split",
                        split_view_enabled=True,
                    )
                    legacy = (
                        state.apps.get_model("bloomerp", "TodoLabel")
                        .objects.using(alias)
                        .create(name="Preserved", color="#123456")
                    )
                    todo_model = state.apps.get_model("bloomerp", "Todo")
                    initiative_model = state.apps.get_model("bloomerp", "Initiative")
                    todo = todo_model.objects.using(alias).create(
                        title="Todo remains labelled"
                    )
                    initiative = initiative_model.objects.using(alias).create(
                        name="Initiative remains labelled"
                    )
                    todo_model._meta.get_field(
                        "labels"
                    ).remote_field.through.objects.using(alias).create(
                        todo_id=todo.pk, todolabel_id=legacy.pk
                    )
                    initiative_model._meta.get_field(
                        "labels"
                    ).remote_field.through.objects.using(alias).create(
                        initiative_id=initiative.pk, todolabel_id=legacy.pk
                    )
                    order = [
                        first,
                        *[name for name in branches if name != first],
                        "0094_merge_list_view_mode_todo_labels",
                    ]
                    for name in order:
                        migration = import_module(
                            f"bloomerp.migrations.{name}"
                        ).Migration(name, "bloomerp")
                        with isolated.schema_editor() as editor:
                            state = migration.apply(state, editor)
                    preferences = state.apps.get_model(
                        "bloomerp", "UserListViewPreference"
                    ).objects.using(alias)
                    self.assertEqual(
                        dict(preferences.values_list("name", "view_mode")),
                        {"Normal": "normal", "Split": "split"},
                    )
                    shared = (
                        state.apps.get_model("bloomerp", "Label")
                        .objects.using(alias)
                        .get(name="Preserved")
                    )
                    assignments = state.apps.get_model(
                        "bloomerp", "ObjectLabel"
                    ).objects.using(alias)
                    self.assertEqual(
                        set(
                            assignments.values_list(
                                "content_type_id", "object_id", "label_id"
                            )
                        ),
                        {
                            (todo_type.pk, str(todo.pk), shared.pk),
                            (initiative_type.pk, str(initiative.pk), shared.pk),
                        },
                    )
                    self.assertNotIn(
                        "bloomerp_todo_label", isolated.introspection.table_names()
                    )
                finally:
                    isolated.close()
                    del connections[alias]
                    del connections.databases[alias]
