from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.core.management.base import CommandError

from bloomerp.tests.base import BaseBloomerpModelTestCase


class TestCreateSdkCommand(BaseBloomerpModelTestCase):
    create_foreign_models = True

    def test_create_sdk_generates_typescript_sdk_files(self):
        """
        The create_sdk management command should generate a typed TypeScript SDK
        with authentication support, model clients, and field metadata.
        """
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "sdk"

            # 1. Generate the TypeScript SDK through the management command entrypoint.
            call_command(
                "create_sdk",
                str(output_path),
                "--language",
                "typescript",
                "--package-name",
                "bloomerp-generated-sdk",
                "--filename",
                "client.ts",
            )

            # 2. Confirm the expected SDK file is created.
            index_file = output_path / "client.ts"

            self.assertTrue(index_file.exists())

            # 3. Confirm the generated SDK includes auth, model typing, and field metadata.
            index_contents = index_file.read_text(encoding="utf-8")

            self.assertIn('type: "basic"', index_contents)
            self.assertIn("export interface Customer", index_contents)
            self.assertIn("export class CustomerApi", index_contents)
            self.assertIn("customersFields", index_contents)
            self.assertIn('"/api/customers/"', index_contents)

    def test_create_sdk_generates_javascript_sdk_file(self):
        """
        The create_sdk management command should generate a JavaScript SDK
        using the shared generator pipeline.
        """
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "sdk"

            # 1. Generate the JavaScript SDK.
            call_command(
                "create_sdk",
                str(output_path),
                "--language",
                "javascript",
                "--filename",
                "client.js",
            )

            # 2. Confirm the JavaScript SDK file is created.
            sdk_file = output_path / "client.js"
            self.assertTrue(sdk_file.exists())

            # 3. Confirm the generated file exposes auth, field metadata, and model clients.
            sdk_contents = sdk_file.read_text(encoding="utf-8")
            self.assertIn("export class BloomerpHttpClient", sdk_contents)
            self.assertIn("export class CustomerApi", sdk_contents)
            self.assertIn("export const customersFields", sdk_contents)
            self.assertIn('super(client, "/api/customers/");', sdk_contents)

    def test_create_sdk_generates_python_sdk_file(self):
        """
        The create_sdk management command should generate a Python SDK with
        typed dictionaries, auth support, and model clients.
        """
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "sdk"

            # 1. Generate the Python SDK.
            call_command(
                "create_sdk",
                str(output_path),
                "--language",
                "python",
                "--filename",
                "client.py",
            )

            # 2. Confirm the Python SDK file is created.
            sdk_file = output_path / "client.py"
            self.assertTrue(sdk_file.exists())

            # 3. Confirm the generated file exposes typed models, metadata, and model clients.
            sdk_contents = sdk_file.read_text(encoding="utf-8")
            self.assertIn("class BloomerpHttpClient:", sdk_contents)
            self.assertIn("class Customer(TypedDict, total=False):", sdk_contents)
            self.assertIn("customers_fields: dict[str, BloomerpFieldMetadata]", sdk_contents)
            self.assertIn('super().__init__(client, "/api/customers/")', sdk_contents)

    def test_create_sdk_uses_language_default_filename_when_filename_is_omitted(self):
        """
        The create_sdk management command should fall back to the selected
        language's default filename when the filename option is omitted.
        """
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "sdk"

            # 1. Generate the Python SDK without providing a filename.
            call_command(
                "create_sdk",
                str(output_path),
                "--language",
                "python",
            )

            # 2. Confirm the Python default filename is used.
            self.assertTrue((output_path / "sdk.py").exists())
            self.assertFalse((output_path / "index.ts").exists())

    def test_create_sdk_can_generate_readme_in_same_folder(self):
        """
        The create_sdk management command should generate an optional README.md
        beside the SDK file when the add-readme flag is enabled.
        """
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "sdk"

            # 1. Generate the SDK with the README option enabled.
            call_command(
                "create_sdk",
                str(output_path),
                "--language",
                "typescript",
                "--filename",
                "index.ts",
                "--add-readme",
            )

            # 2. Confirm both files exist in the same folder.
            index_file = output_path / "index.ts"
            readme_file = output_path / "README.md"

            self.assertTrue(index_file.exists())
            self.assertTrue(readme_file.exists())

            # 3. Confirm the README explains the main CRUD and filtering flows.
            readme_contents = readme_file.read_text(encoding="utf-8")
            self.assertIn("## Read One", readme_contents)
            self.assertIn("## Create", readme_contents)
            self.assertIn("## Update", readme_contents)
            self.assertIn("## Delete", readme_contents)
            self.assertIn("## Filter / List", readme_contents)
            self.assertIn('await sdk.customers.retrieve(1);', readme_contents)
            self.assertIn('await sdk.customers.list({', readme_contents)

    def test_create_sdk_rejects_unsupported_languages(self):
        """
        The create_sdk management command should reject languages that are not
        explicitly supported yet.
        """
        with TemporaryDirectory() as temp_dir:
            # 1. Attempt to generate an unsupported SDK language.
            with self.assertRaises(CommandError):
                call_command(
                    "create_sdk",
                    temp_dir,
                    "--language",
                    "ruby",
                )
