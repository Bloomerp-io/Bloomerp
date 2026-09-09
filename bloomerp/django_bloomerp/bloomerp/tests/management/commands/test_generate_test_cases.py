from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.apps import apps
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from bloomerp.management.commands.generate_test_cases import (
    GENERATED_FILE_HEADER,
    SUPPORTED_FUNCTIONALITIES,
    Command,
    GeneratedTestCase,
)
from bloomerp.models.project_management.todo import Todo


class GenerateTestCasesCommandTests(SimpleTestCase):
    def setUp(self):
        self.command = Command(stdout=StringIO())
        self.app_config = apps.get_app_config("bloomerp")

    def test_functionality_selection_is_normalized_and_validated(self):
        """
        Use case: A developer selects categories on the command line.
        Expected result: Names are normalized, deduplicated, and validated.
        """
        # 1. Normalize hyphenated names and remove duplicates in input order.
        self.assertEqual(
            self.command._parse_functionalities(
                "views, workflow-nodes, views"
            ),
            ("views", "workflow_nodes"),
        )

        # 2. Expand the explicit all alias to every supported category.
        self.assertEqual(
            self.command._parse_functionalities("all"),
            SUPPORTED_FUNCTIONALITIES,
        )

        # 3. Reject unknown categories with an actionable command error.
        with self.assertRaisesRegex(CommandError, "Unsupported functionality"):
            self.command._parse_functionalities("views,unknown")

    def test_model_target_mirrors_its_source_directory(self):
        """
        Use case: A model lives in a nested source package.
        Expected result: Its generated test mirrors that nesting under tests/models.
        """
        # 1. Discover the real Todo model test skeleton.
        generated = self.command._discover_models(self.app_config)
        todo_case = next(
            test_case
            for test_case in generated
            if "from bloomerp.models.project_management.todo import Todo"
            in test_case.content
        )

        # 2. Confirm its source nesting and non-redundant name are preserved.
        relative_target = todo_case.target.relative_to(self.app_config.path)
        self.assertEqual(
            relative_target,
            Path("tests/models/project_management/test_todo_model.py"),
        )
        self.assertIn("class TestTodoModel(BloomerpModelTestCase):", todo_case.content)

    def test_route_discovery_groups_registrations_by_source_definition(self):
        """
        Use case: One view implementation is registered under multiple route names.
        Expected result: The command emits one nested test class for that implementation.
        """
        # 1. Discover view skeletons from the populated application router.
        generated = self.command._discover_views(self.app_config)
        targets = [test_case.target for test_case in generated]

        # 2. Confirm each implementation has one unique nested target.
        self.assertEqual(len(targets), len(set(targets)))
        self.assertTrue(
            any("tests/views/generic/" in target.as_posix() for target in targets)
        )

        # 3. Confirm route expansions are represented by one selected context.
        self.assertTrue(all("route_url_names" not in case.content for case in generated))
        generic_model_case = next(
            case for case in generated if "class TestBloomerpListView" in case.content
        )
        self.assertIn("BloomerpModelViewTestCase", generic_model_case.content)
        self.assertIn("model = None", generic_model_case.content)

        # 4. Populate a model automatically when the route has exactly one model.
        submit_case = next(
            case for case in generated if "class TestSubmitFormView" in case.content
        )
        self.assertIn("from bloomerp.models.forms.form import Form", submit_case.content)
        self.assertIn("BloomerpDetailViewTestCase", submit_case.content)
        self.assertIn("view_name = 'submit'", submit_case.content)
        self.assertIn("model = Form", submit_case.content)
        self.assertIn(
            '"""Tests class `SubmitFormView` from '
            '`bloomerp/views/forms/submit.py`."""',
            submit_case.content,
        )
        self.assertIn("    ExpectedResult,", submit_case.content)
        self.assertIn("    RequestSetup,", submit_case.content)
        self.assertIn("    ModelRequestSetup,", submit_case.content)
        self.assertIn(
            "def get_request_setups(self) -> list[RequestSetup]:",
            submit_case.content,
        )

        # 5. Include all API route families with their specialized base classes.
        api_case = next(
            case
            for case in generated
            if "class TestBloomerpApiRootView" in case.content
        )
        self.assertIn("BloomerpAPIViewTestCase", api_case.content)
        self.assertIn("    ExpectedResult,", api_case.content)
        self.assertIn("    RequestSetup,", api_case.content)

        api_model_case = next(
            case
            for case in generated
            if "class TestBloomerpListApiView" in case.content
        )
        self.assertIn("BloomerpAPIModelViewTestCase", api_model_case.content)
        self.assertIn("    ModelRequestSetup,", api_model_case.content)

        api_detail_case = next(
            case
            for case in generated
            if "class TestBloomerpDetailApiView" in case.content
        )
        self.assertIn("BloomerpAPIDetailViewTestCase", api_detail_case.content)
        self.assertIn("    ModelRequestSetup,", api_detail_case.content)

    def test_component_skeleton_imports_request_scenario_classes(self):
        """
        Use case: A developer implements a generated component test.
        Expected result: The request setup and expected-result classes are imported.
        """
        # 1. Render a representative component skeleton.
        content = self.command._render_request_test(
            base_class="BloomerpComponentTestCase",
            class_name="TestExampleComponent",
            view_name="components_example",
            source_file="example/components/example.py",
            view_definition="example_component",
            view_kind="function",
        )

        # 2. Confirm all classes needed for request scenarios are ready to use.
        self.assertIn("    BloomerpComponentTestCase,", content)
        self.assertIn("    ExpectedResult,", content)
        self.assertIn("    RequestSetup,", content)
        self.assertIn(
            '"""Tests function `example_component` from '
            '`example/components/example.py`."""',
            content,
        )
        self.assertIn("def get_request_setups(self) -> list[RequestSetup]:", content)

    def test_component_discovery_fails_when_a_source_module_cannot_import(self):
        """
        Use case: A component module contains a broken import.
        Expected result: Generation fails instead of silently omitting its routes.
        """
        with patch.object(
            self.command,
            "_import_source_modules",
            side_effect=CommandError("Unable to import broken component"),
        ):
            with self.assertRaisesRegex(CommandError, "broken component"):
                self.command._discover_components(self.app_config)

    def test_registry_ownership_is_inferred_from_implementations(self):
        """
        Use case: Registries do not expose developer-authored app ownership metadata.
        Expected result: Workflow-node and dataview tests are assigned by class module.
        """
        # 1. Discover both kinds of registry-backed skeleton.
        workflow_cases = self.command._discover_workflow_nodes(self.app_config)
        dataview_cases = self.command._discover_dataviews(self.app_config)

        # 2. Confirm known built-in registrations are assigned to the Bloomerp app.
        self.assertTrue(
            any("node_id = 'ON_OBJECT_CREATE'" in case.content for case in workflow_cases)
        )
        object_create_case = next(
            case
            for case in workflow_cases
            if "node_id = 'CREATE_OBJECT'" in case.content
        )
        self.assertIn(
            "from bloomerp.automation.actions.create_object import CreateObjectExecutor",
            object_create_case.content,
        )
        self.assertIn("executor_class = CreateObjectExecutor", object_create_case.content)
        self.assertIn("WorkflowNodeSimulation", object_create_case.content)
        self.assertTrue(
            any("dataview_key = 'table'" in case.content for case in dataview_cases)
        )

    def test_writing_respects_dry_run_existing_files_and_force(self):
        """
        Use case: A developer previews and then regenerates a test skeleton.
        Expected result: Dry-run is inert, existing work is safe, and force is explicit.
        """
        with TemporaryDirectory() as directory:
            target = Path(directory) / "tests" / "views" / "nested" / "test_demo_view.py"
            test_case = GeneratedTestCase(
                functionality="views",
                target=target,
                content=GENERATED_FILE_HEADER + "generated = True\n",
            )

            # 1. Previewing reports creation without touching the filesystem.
            self.assertEqual(
                self.command._write_test_case(test_case, force=False, dry_run=True),
                "created",
            )
            self.assertFalse(target.exists())

            # 2. Creating writes the test and package markers.
            self.assertEqual(
                self.command._write_test_case(test_case, force=False, dry_run=False),
                "created",
            )
            self.assertEqual(target.read_text(encoding="utf-8"), test_case.content)
            self.assertTrue((target.parent / "__init__.py").exists())

            # 3. Existing developer work is skipped unless force is supplied.
            target.write_text("developer_work = True\n", encoding="utf-8")
            self.assertEqual(
                self.command._write_test_case(test_case, force=False, dry_run=False),
                "skipped",
            )
            self.assertEqual(
                target.read_text(encoding="utf-8"), "developer_work = True\n"
            )

            # 4. Generated files with developer work are protected too.
            customized_generated_content = GENERATED_FILE_HEADER + "old = True\n"
            target.write_text(customized_generated_content, encoding="utf-8")
            self.assertEqual(
                self.command._write_test_case(test_case, force=False, dry_run=False),
                "skipped",
            )
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                customized_generated_content,
            )

            # 5. Empty generated request skeletons can be refreshed safely.
            generated_skeleton = (
                GENERATED_FILE_HEADER
                + "class TestExample:\n"
                + "    def get_request_setups(self):\n"
                + "        # Add only the route scenarios this callable needs.\n"
                + "        return []\n"
            )
            target.write_text(generated_skeleton, encoding="utf-8")
            self.assertEqual(
                self.command._write_test_case(test_case, force=False, dry_run=False),
                "overwritten",
            )
            self.assertEqual(target.read_text(encoding="utf-8"), test_case.content)

            # 6. The explicit force option replaces handwritten targets.
            target.write_text("developer_work = True\n", encoding="utf-8")
            self.assertEqual(
                self.command._write_test_case(test_case, force=True, dry_run=False),
                "overwritten",
            )
            self.assertEqual(target.read_text(encoding="utf-8"), test_case.content)

    def test_model_discovery_uses_the_configured_model_class(self):
        """
        Use case: A model skeleton is generated for a concrete model.
        Expected result: The class imports and assigns the exact model class.
        """
        # 1. Locate the generated Todo skeleton by its source class.
        generated = self.command._discover_models(self.app_config)
        todo_case = next(case for case in generated if "model = Todo" in case.content)

        # 2. Confirm the model source module remains the source of truth.
        self.assertEqual(Todo.__module__, "bloomerp.models.project_management.todo")
        self.assertIn(f"from {Todo.__module__} import Todo", todo_case.content)
