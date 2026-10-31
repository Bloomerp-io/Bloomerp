import runpy
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.views import View
from rest_framework import serializers

from bloomerp.models.definition import (
    ApiAccessSettings,
    ApiNesting,
    ApiSettings,
    BloomerpModelConfig,
)
from bloomerp.permissions.definition import (
    AccessRule,
    BloomerpPermission,
    RowPolicyRuleCondition,
    RowPolicyRuleContent,
)
from bloomerp.router import BloomerpRouteRegistry, router
from bloomerp.sdk.definition import SdkEndpoint
from bloomerp.sdk.javascript import JavaScriptSdkGenerator
from bloomerp.sdk.python import PythonSdkGenerator
from bloomerp.sdk.typescript import TypescriptSdkGenerator
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels


class TestCreateSdkCommand(BaseBloomerpTestCaseWithModels):
    create_foreign_models = True

    def _set_nested_sdk_config(self):
        self.CustomerModel.bloomerp_config = BloomerpModelConfig(
            api_settings=ApiSettings(
                enable_auto_generation=True,
                access=ApiAccessSettings(
                    anonymous=[
                        AccessRule(
                            row_permissions=[
                                RowPolicyRuleContent(
                                    permissions=[BloomerpPermission.VIEW],
                                    conditions=[RowPolicyRuleCondition(field="__all__")],
                                )
                            ],
                            field_permissions={
                                "id": [BloomerpPermission.VIEW],
                                "first_name": [BloomerpPermission.VIEW],
                                "country": [BloomerpPermission.VIEW],
                            },
                        )
                    ]
                ),
                nesting=[
                    ApiNesting(for_field="country", fields=["name"], on_action=["read"]),
                ],
            )
        )
        self.CountryModel.bloomerp_config = BloomerpModelConfig(
            api_settings=ApiSettings(
                enable_auto_generation=True,
                access=ApiAccessSettings(
                    anonymous=[
                        AccessRule(
                            row_permissions=[
                                RowPolicyRuleContent(
                                    permissions=[BloomerpPermission.VIEW],
                                    conditions=[RowPolicyRuleCondition(field="__all__")],
                                )
                            ],
                            field_permissions={
                                "id": [BloomerpPermission.VIEW],
                                "name": [BloomerpPermission.VIEW],
                            },
                        )
                    ]
                ),
            )
        )

    def test_create_sdk_generates_typescript_sdk_files(self):
        """
        The create_sdk management command should generate a typed TypeScript SDK
        with authentication support, model clients, and field metadata.
        """
        self._set_nested_sdk_config()
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

            self.assertIn('type: "session"', index_contents)
            self.assertIn("export class AuthApi", index_contents)
            self.assertIn("export class BloomerpHttpError", index_contents)
            self.assertIn("super(BloomerpHttpError.buildMessage(response, body));", index_contents)
            self.assertIn("private static buildMessage<TBody>(response: Response, body?: TBody)", index_contents)
            self.assertIn("export interface Customer", index_contents)
            self.assertIn("export class CustomerApi", index_contents)
            self.assertIn("customersFields", index_contents)
            self.assertIn("customersPublicAccess", index_contents)
            self.assertIn("nesting: BloomerpModelNestingMetadata[]", index_contents)
            self.assertIn("export interface BloomerpFieldChoiceMetadata", index_contents)
            self.assertIn('"choices": [', index_contents)
            self.assertIn('country: string | null | Country;', index_contents)
            self.assertIn('"forField": "country"', index_contents)
            self.assertIn("bloomerpAuthStrategyTypes", index_contents)
            self.assertIn('"/api/customers/"', index_contents)
            self.assertIn("login(payload: BloomerpAuthLoginPayload", index_contents)
            self.assertIn("fetchOptions?: Record<string, unknown>", index_contents)
            self.assertIn("globalThis.fetch(input, init)", index_contents)
            self.assertIn("return normalizeListResponse(response);", index_contents)
            self.assertIn("createMany(payloads: TCreate[]", index_contents)
            self.assertIn("createMany: boolean;", index_contents)
            self.assertIn('"createMany":true', index_contents.replace(" ", ""))

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
            self.assertIn("export class AuthApi", sdk_contents)
            self.assertIn("this.auth = new AuthApi(this.client);", sdk_contents)
            self.assertIn("listResults(query = undefined, options = undefined)", sdk_contents)
            self.assertIn("export const bloomerpAuthStrategyTypes", sdk_contents)
            self.assertIn("export class CustomerApi", sdk_contents)
            self.assertIn("export const customersFields", sdk_contents)
            self.assertIn("export const customersPublicAccess", sdk_contents)
            self.assertIn("choices: BloomerpFieldChoice[] | null", sdk_contents)
            self.assertIn('"choices":[', sdk_contents.replace(" ", ""))
            self.assertIn('super(client, "/api/customers/");', sdk_contents)
            self.assertIn("globalThis.fetch(input, init)", sdk_contents)
            self.assertIn("createMany(payloads, options = undefined)", sdk_contents)
            self.assertIn('"createMany":true', sdk_contents.replace(" ", ""))

    def test_create_sdk_generates_python_sdk_file(self):
        """
        The create_sdk management command should generate a Python SDK with
        typed dictionaries, auth support, and model clients.
        """
        self._set_nested_sdk_config()
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
            self.assertIn("class AuthApi:", sdk_contents)
            self.assertIn("self.auth = AuthApi(self.client)", sdk_contents)
            self.assertIn("class Customer(TypedDict, total=False):", sdk_contents)
            self.assertIn("class ModelApi(Generic[TModel, TId, TCreate, TUpdate]):", sdk_contents)
            self.assertIn("def retrieve(self, object_id: TId, options: BloomerpRequestOptions | None = None) -> TModel:", sdk_contents)
            self.assertIn("def list_results(", sdk_contents)
            self.assertIn("country: str | None | Country", sdk_contents)
            self.assertIn("'forField': 'country'", sdk_contents)
            self.assertIn("customers_fields: dict[str, BloomerpFieldMetadata]", sdk_contents)
            self.assertIn("choices: list[dict[str, Any]] | None", sdk_contents)
            self.assertIn("'choices': [", sdk_contents)
            self.assertIn("customers_public_access: dict[str, Any]", sdk_contents)
            self.assertIn('super().__init__(client, "/api/customers/")', sdk_contents)
            self.assertIn("def create_many(self, payloads: list[TCreate]", sdk_contents)
            self.assertIn("'createMany': True", sdk_contents)

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
            self.assertIn("## Session Auth", readme_contents)
            self.assertIn("## Read One", readme_contents)
            self.assertIn("## Create", readme_contents)
            self.assertIn("## Filter / List", readme_contents)
            self.assertIn("## Inspect Field Options", readme_contents)
            self.assertIn("## Handle Validation Errors", readme_contents)
            self.assertIn("await sdk.auth.login({", readme_contents)
            self.assertIn('const page = await sdk.customers.list({', readme_contents)
            self.assertIn("sdk.metadata.models.<model>.fields.<field>.choices", readme_contents)
            self.assertIn("BloomerpHttpError", readme_contents)

    def test_create_sdk_can_limit_generated_models_to_selected_apps(self):
        """
        The create_sdk management command should allow filtering generated SDK
        models by a comma-separated list of app names.
        """
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "sdk"

            call_command(
                "create_sdk",
                str(output_path),
                "--language",
                "typescript",
                "--filename",
                "index.ts",
                "--apps",
                "django.contrib.auth",
            )

            index_contents = (output_path / "index.ts").read_text(encoding="utf-8")

            self.assertNotIn("export interface Customer", index_contents)
            self.assertNotIn("export class CustomerApi", index_contents)

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


    def test_custom_sdk_contracts_and_transport(self) -> None:
        """
        Use case: Custom routes expose single or multiple methods with model-dependent serializers.
        Expected result: All languages preserve each method's types and request transport.
        """
        # 1. Register a deferred detail operation, a GET query, and an opted-out route.
        class ItemSerializer(serializers.Serializer):
            """Nested response values with literal choices and nullable text."""

            state = serializers.ChoiceField(choices=["ready", "done"])
            note = serializers.CharField(required=False, allow_null=True)
            secret = serializers.CharField(write_only=True)

        class OutputSerializer(serializers.Serializer):
            """Return nested records and server-owned identifiers."""

            items = ItemSerializer(many=True)
            id = serializers.IntegerField(read_only=True)
            owner = serializers.PrimaryKeyRelatedField(read_only=True)

        class QuerySerializer(serializers.Serializer):
            """Describe query-string values accepted by the search endpoint."""

            term = serializers.CharField()
            tags = serializers.ListField(child=serializers.CharField(), required=False)

        resolved_models: list[type[Model] | None] = []

        def input_for_model(model: type[Model] | None) -> type[serializers.BaseSerializer]:
            """Build a serializer using the model attached to this route."""
            resolved_models.append(model)
            meta = type("Meta", (), {"model": model, "fields": ["id", "first_name"]})
            return type("CustomerInputSerializer", (serializers.ModelSerializer,), {"Meta": meta})

        def endpoint(request: HttpRequest, **kwargs: object) -> HttpResponse:
            """Supply a local route fixture without invoking a real server."""
            return HttpResponse()

        class MultiMethodView(View):
            """Declare a fixture route that supports both reading and writing."""

            def get(self, request: HttpRequest, **kwargs: object) -> HttpResponse:
                """Represent the query operation without contacting a real server."""
                return HttpResponse()

            def post(self, request: HttpRequest, **kwargs: object) -> HttpResponse:
                """Represent the JSON operation without contacting a real server."""
                return HttpResponse()

        registry = BloomerpRouteRegistry()
        registry._auto_imported = True
        registry.register(
            path="/post/", route_type="api_detail", models=[self.CustomerModel], url_name="post",
            sdk=SdkEndpoint(method="POST", input_serializer=input_for_model, output_serializer=OutputSerializer),
        )(endpoint)
        registry.register(
            path="/action/", route_type="api_detail", models=[self.CustomerModel], url_name="action",
            sdk=[
                SdkEndpoint(method="GET", input_serializer=QuerySerializer, output_serializer=OutputSerializer),
                SdkEndpoint(method="POST", input_serializer=input_for_model, output_serializer=ItemSerializer),
            ],
        )(MultiMethodView)
        # Exercise the path used when models arrive after router discovery.
        registry.routes.clear()
        registry.register_routes_for_model(self.CustomerModel)
        registry.register(
            path="search/", route_type="api", url_name="search",
            sdk=[SdkEndpoint(method="GET", input_serializer=QuerySerializer, output_serializer=OutputSerializer)],
        )(endpoint)
        registry.register(path="untyped/", route_type="api", url_name="untyped")(endpoint)
        self.assertEqual(resolved_models, [])

        # 2. Generate complete clients; verify exclusion, direction, nested types, and app filtering.
        with TemporaryDirectory() as directory, patch.object(router, "filter", return_value=registry.routes):
            for generator_class in (TypescriptSdkGenerator, JavaScriptSdkGenerator, PythonSdkGenerator):
                generator = generator_class(directory)
                source = generator.render_source([])
                self.assertNotIn("untyped", source)
                self.assertNotIn("secret", source)
                self.assertIn("CustomCustomersPostOutputItemsItem", source)
                owner_declaration = {
                    "python": "'owner': str | int,",
                    "typescript": '"owner": string | number;',
                    "javascript": "@property {string | number} owner",
                }[generator.language]
                self.assertIn(owner_declaration, source)
                self.assertIn("/api/customers/<int_or_uuid:pk>/post/", source)
                self.assertNotIn("/api/customers/", generator_class(directory, app_labels=["auth"]).render_source([]))
                suffix = {"typescript": "ts", "javascript": "mjs", "python": "py"}[generator.language]
                target = Path(directory) / f"client.{suffix}"
                target.write_text(source, encoding="utf-8")

                # 3. Execute generated methods to prove URL encoding, JSON/query placement, and options.
                if generator.language == "python":
                    namespace = runpy.run_path(str(target))
                    sdk = namespace["BloomerpSdk"]("https://example.test")
                    sdk.client.request = Mock(return_value={"items": [], "id": 1})
                    result = sdk.custom.customers_post({"first_name": "Ada"}, {"pk": "a/b ?"}, {"headers": {"X-Test": "yes"}})
                    self.assertEqual(result, {"items": [], "id": 1})
                    sdk.client.request.assert_called_with(
                        "/api/customers/a%2Fb%20%3F/post/", method="POST", data={"first_name": "Ada"},
                        options={"headers": {"X-Test": "yes"}},
                    )
                    sdk.custom.search({"term": "Ada", "tags": ["a", "b"]})
                    sdk.client.request.assert_called_with(
                        "/api/search/", method="GET", query={"term": "Ada", "tags": ["a", "b"]}, options=None,
                    )
                    self.assertEqual(set(namespace["CustomCustomersActionGetInput"].__annotations__), {"term", "tags"})
                    self.assertEqual(set(namespace["CustomCustomersActionPostInput"].__annotations__), {"first_name"})
                    self.assertEqual(set(namespace["CustomCustomersActionGetOutput"].__annotations__), {"items", "id", "owner"})
                    self.assertEqual(set(namespace["CustomCustomersActionPostOutput"].__annotations__), {"state", "note"})
                    sdk.custom.customers_action_get({"term": "Ada"}, {"pk": "a/b ?"})
                    sdk.client.request.assert_called_with(
                        "/api/customers/a%2Fb%20%3F/action/", method="GET", query={"term": "Ada"}, options=None,
                    )
                    sdk.client.request.return_value = {"state": "ready"}
                    result = sdk.custom.customers_action_post({"first_name": "Ada"}, {"pk": "a/b ?"})
                    self.assertEqual(result, {"state": "ready"})
                    sdk.client.request.assert_called_with(
                        "/api/customers/a%2Fb%20%3F/action/", method="POST", data={"first_name": "Ada"}, options=None,
                    )
                elif shutil.which("node"):
                    script = """
import assert from 'node:assert/strict';
const { BloomerpSdk, BloomerpHttpError } = await import(process.argv[1]);
const requests = [];
/** Capture generated HTTP requests without contacting a server.
 * @param {RequestInfo | URL} input Request URL.
 * @param {RequestInit} init Request options.
 * @returns {Promise<Response>} Simulated API response.
 */
async function capture(input, init) {
    requests.push(new Request(input, init));
    if (String(input).includes('/action/') && init.method === 'POST') {
        return Response.json({state: 'ready'});
    }
    return Response.json({ items: [], id: 1 });
}
const sdk = new BloomerpSdk({baseUrl: 'https://example.test', fetch: capture,
    auth: {type: 'session', csrf: {token: 'csrf-token'}}});
await sdk.custom.customersPost({first_name: 'Ada'}, {pk: 'a/b ?'}, {headers: {'X-Test': 'yes'}});
assert.equal(requests[0].url, 'https://example.test/api/customers/a%2Fb%20%3F/post/');
assert.equal(requests[0].method, 'POST');
assert.equal(requests[0].headers.get('X-CSRFToken'), 'csrf-token');
assert.equal(requests[0].headers.get('X-Test'), 'yes');
assert.deepEqual(await requests[0].json(), {first_name: 'Ada'});
await sdk.custom.search({term: 'Ada', tags: ['a', 'b']});
assert.equal(requests[1].method, 'GET');
assert.equal(requests[1].body, null);
assert.deepEqual(new URL(requests[1].url).searchParams.getAll('tags'), ['a', 'b']);
const read = await sdk.custom.customersActionGet({term: 'Ada'}, {pk: 'a/b ?'});
assert.deepEqual(read, {items: [], id: 1});
assert.equal(requests[2].url, 'https://example.test/api/customers/a%2Fb%20%3F/action/?term=Ada');
assert.equal(requests[2].method, 'GET');
assert.equal(requests[2].body, null);
const written = await sdk.custom.customersActionPost({first_name: 'Ada'}, {pk: 'a/b ?'});
assert.deepEqual(written, {state: 'ready'});
assert.equal(requests[3].url, 'https://example.test/api/customers/a%2Fb%20%3F/action/');
assert.equal(requests[3].method, 'POST');
assert.equal(requests[3].headers.get('X-CSRFToken'), 'csrf-token');
assert.deepEqual(await requests[3].json(), {first_name: 'Ada'});
"""
                    completed = subprocess.run(
                        [shutil.which("node"), "--experimental-transform-types", "--input-type=module", "-e", script, target.as_uri()],
                        capture_output=True, text=True, check=False,
                    )
                    self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(resolved_models, [self.CustomerModel] * 6)

    def test_custom_sdk_rejects_invalid_route_contracts(self) -> None:
        """
        Use case: A route declares an incomplete or unsupported SDK contract.
        Expected result: Registration fails explicitly instead of generating a broken client.
        """
        # 1. Require both serializers and a supported method.
        with self.assertRaises(TypeError):
            SdkEndpoint(method="POST", input_serializer=None, output_serializer=serializers.Serializer)
        with self.assertRaises(ValueError):
            SdkEndpoint(method="TRACE", input_serializer=serializers.Serializer, output_serializer=serializers.Serializer)

        # 2. Keep SDK discovery limited to API paths.
        def endpoint(request: HttpRequest) -> HttpResponse:
            """Supply a local registration fixture."""
            return HttpResponse()

        registry = BloomerpRouteRegistry()
        contract = SdkEndpoint(method="POST", input_serializer=serializers.Serializer, output_serializer=serializers.Serializer)
        with self.assertRaises(ValueError):
            registry.register(path="ordinary/", sdk=contract)(endpoint)
        with self.assertRaises(ValueError):
            registry.register(re_path="^api/regex/$", route_type="api", sdk=contract)(endpoint)

        # 3. Reject ambiguous lists and validate every declared view method.
        with self.assertRaisesRegex(ValueError, "Duplicate SDK method: POST"):
            registry.register(path="duplicate/", route_type="api", sdk=[contract, contract])(endpoint)
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            registry.register(path="empty/", route_type="api", sdk=[])(endpoint)
        with self.assertRaises(TypeError):
            registry.register(path="invalid/", route_type="api", sdk=[None])(endpoint)

        class GetOnlyView(View):
            """Provide a view missing the requested POST implementation."""

            def get(self, request: HttpRequest) -> HttpResponse:
                """Serve the only supported operation for registration validation."""
                return HttpResponse()

        read_contract = SdkEndpoint(method="GET", input_serializer=serializers.Serializer, output_serializer=serializers.Serializer)
        with self.assertRaisesRegex(ValueError, "POST is not implemented"):
            registry.register(path="unsupported/", route_type="api", sdk=[read_contract, contract])(GetOnlyView)
