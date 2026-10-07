"""Exercise file upload/link contracts and their source/destination permission boundaries."""

import base64
from typing import Any
from uuid import uuid4

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import override_settings
from django.urls import path
from drf_spectacular.generators import SchemaGenerator
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from bloomerp.filters.definition import FilterCondition
from bloomerp.models import File, FileFolder
from bloomerp.permissions.definition import BloomerpPermission, RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.router import router
from bloomerp.tests.base import BloomerpAPIViewTestCase, ExpectedResult, RequestScenario
from bloomerp.views.mcp.link_file import AssistantFileLinkView
from bloomerp.views.api.files.upload_file import AssistantFileUploadView


class TestAssistantFiles(BloomerpAPIViewTestCase):
    """Test real API views with temporary media and object-specific file permissions."""

    view_name = "api_assistant_file_upload"
    auto_create_customers = False

    def extendedSetup(self) -> None:
        """Create two destinations and a reusable uploaded file in the general library."""
        self.customer = self.create_customer("Lisa", "Larsen", 30)
        self.other = self.create_customer("Other", "Person", 31)
        self.content_type = ContentType.objects.get_for_model(self.CustomerModel)
        self.file = File.objects.create(
            file=SimpleUploadedFile("existing.txt", b"original bytes"), persisted=True
        )
        self.destination = {
            "model_label": self.CustomerModel._meta.label,
            "object_id": str(self.customer.pk),
        }

    def uploaded_library_file(self, response: HttpResponse) -> bool:
        """Verify a routed upload persists one file with the expected bytes."""
        payload = response.json()
        uploaded = File.objects.exclude(pk=self.file.pk).get()
        self.assertEqual(uploaded.file.read(), b"hello")
        self.assertIn(str(uploaded.pk), str(payload))
        return True

    def denied_upload_preserves_library(self, response: HttpResponse) -> bool:
        """Verify denied or malformed uploads leave the existing library intact."""
        self.assertEqual(File.objects.count(), 1)
        return True

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Exercise upload routing and authentication alongside focused permission integrations."""
        return [
            RequestScenario(
                name="Administrator uploads JSON to the library",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data=self.upload_data(),
                expected=ExpectedResult(
                    status_code=201, response_validators=self.uploaded_library_file
                ),
            ),
            RequestScenario(
                name="Anonymous upload is denied",
                method="POST",
                content_type="application/json",
                data=self.upload_data(),
                expected=ExpectedResult(
                    status_code=401,
                    response_validators=self.denied_upload_preserves_library,
                ),
            ),
        ]

    def call(
        self,
        data: dict[str, Any],
        *,
        upload: bool = False,
        user: Any = None,
        multipart: bool = False,
    ) -> Response:
        """Invoke the production DRF endpoint with authenticated JSON or multipart input."""
        request = APIRequestFactory().post(
            "/", data, format="multipart" if multipart else "json"
        )
        if user is not None:
            force_authenticate(request, user=user)
        view = AssistantFileUploadView if upload else AssistantFileLinkView
        return view.as_view()(request)

    def upload_data(self) -> dict[str, str]:
        """Build a JSON upload without exposing a filesystem path to the endpoint."""
        return {
            "filename": "hello.txt",
            "content_base64": base64.b64encode(b"hello").decode(),
        }

    def grant_destination(self, *, group: bool = False) -> None:
        """Grant files access only on the selected row, directly or through a group."""
        permissions = [
            BloomerpPermission.VIEW,
            BloomerpPermission.ADD,
            BloomerpPermission.CHANGE,
        ]
        policy = PolicyManager.create_policy(
            model_or_content_type=self.CustomerModel,
            field_permissions={"files": permissions},
            row_permissions=[
                RowPolicyRuleContent(
                    permissions=permissions,
                    conditions=[
                        FilterCondition(
                            field_path="id",
                            lookup_id="equals",
                            value=str(self.customer.pk),
                        )
                    ],
                )
            ],
        )
        if group:
            team = Group.objects.create(name="File team")
            team.user_set.add(self.normal_user)
            policy.groups.add(team)
        else:
            policy.users.add(self.normal_user)

    def test_upload_json_and_multipart_to_library_or_object(self) -> None:
        """Upload real bytes and return compact IDs for library and direct object placement."""
        response = self.call(self.upload_data(), upload=True, user=self.admin_user)
        self.assertEqual(response.status_code, 201, response.data)
        uploaded = File.objects.get(pk=response.data["file_id"])
        self.assertEqual(uploaded.file.read(), b"hello")
        self.assertIsNone(uploaded.object_id)
        response = self.call(
            {
                **self.destination,
                "file": SimpleUploadedFile("object.txt", b"object bytes"),
            },
            upload=True,
            multipart=True,
            user=self.admin_user,
        )
        self.assertEqual(response.status_code, 201, response.data)
        uploaded = File.objects.get(pk=response.data["file_id"])
        self.assertEqual(uploaded.object_id, str(self.customer.pk))
        self.assertEqual(uploaded.folder.object_id, str(self.customer.pk))

    def test_link_existing_file_and_repeat_without_copying(self) -> None:
        """Attach a chat upload to an object idempotently, retaining the stored bytes."""
        path = self.file.file.name
        count = File.objects.count()
        for _ in range(2):
            response = self.call(
                {"file_id": str(self.file.pk), **self.destination}, user=self.admin_user
            )
            self.assertEqual(response.status_code, 200, response.data)
        self.file.refresh_from_db()
        self.assertEqual(self.file.file.name, path)
        self.assertEqual(File.objects.count(), count)
        self.assertTrue(self.customer.files.filter(pk=self.file.pk).exists())

    def test_folder_scope_and_relocation(self) -> None:
        """Infer a destination object from its folder and reject mismatched explicit identities."""
        folder = FileFolder.objects.create(
            name="Documents",
            content_type=self.content_type,
            object_id=str(self.customer.pk),
        )
        response = self.call(
            {"file_id": str(self.file.pk), "folder_id": folder.pk}, user=self.admin_user
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.file.refresh_from_db()
        self.assertEqual(self.file.object_id, str(self.customer.pk))
        response = self.call(
            {
                "file_id": str(self.file.pk),
                "folder_id": folder.pk,
                **self.destination,
                "object_id": str(self.other.pk),
            },
            user=self.admin_user,
        )
        self.assertEqual(response.status_code, 400)
        library = FileFolder.objects.create(name="Library")
        response = self.call(
            {"file_id": str(self.file.pk), "folder_id": library.pk},
            user=self.admin_user,
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.file.refresh_from_db()
        self.assertIsNone(self.file.object_id)
        self.assertEqual(self.file.folder_id, library.pk)

    def test_invalid_uploads_do_not_create_records(self) -> None:
        """Reject malformed bytes, oversized files, incomplete destinations and missing objects."""
        count = File.objects.count()
        for data in [
            {**self.upload_data(), "content_base64": "invalid!"},
            {**self.upload_data(), "filename": "../escape.txt"},
            {**self.upload_data(), "content_base64": ""},
            {**self.upload_data(), "model_label": self.CustomerModel._meta.label},
            {**self.upload_data(), "model_label": "missing.Model", "object_id": "1"},
        ]:
            with self.subTest(data=data):
                self.assertEqual(
                    self.call(data, upload=True, user=self.admin_user).status_code, 400
                )
        with override_settings(BLOOMERP_AGENT_UPLOAD_MAX_BYTES=2):
            self.assertEqual(
                self.call(
                    self.upload_data(), upload=True, user=self.admin_user
                ).status_code,
                400,
            )
        self.assertEqual(
            self.call(
                {"file_id": str(uuid4()), **self.destination}, user=self.admin_user
            ).status_code,
            404,
        )
        self.assertEqual(File.objects.count(), count)

    def test_source_and_destination_permissions_are_both_required(self) -> None:
        """Reject anonymous/no-policy callers and prevent a destination grant from authorizing a source."""
        data = {"file_id": str(self.file.pk), **self.destination}
        self.assertIn(self.call(data).status_code, (401, 403))
        self.assertEqual(self.call(data, user=self.normal_user).status_code, 403)
        self.assertEqual(
            self.call(
                self.upload_data(), upload=True, user=self.normal_user
            ).status_code,
            403,
        )
        self.grant_destination()
        self.assertEqual(self.call(data, user=self.normal_user).status_code, 403)
        self.normal_user.user_permissions.add(
            *Permission.objects.filter(
                content_type=ContentType.objects.get_for_model(File),
                codename__in=["view_file", "change_file"],
            )
        )
        self.normal_user = type(self.normal_user).objects.get(pk=self.normal_user.pk)
        response = self.call(data, user=self.normal_user)
        self.assertEqual(response.status_code, 200, response.data)
        response = self.call(
            {**data, "object_id": str(self.other.pk)}, user=self.normal_user
        )
        self.assertEqual(response.status_code, 403)
        self.file.refresh_from_db()
        self.assertEqual(self.file.object_id, str(self.customer.pk))

    def test_group_policy_allows_direct_object_upload(self) -> None:
        """Use a group-based row/field grant without requiring unrelated library upload access."""
        self.grant_destination(group=True)
        response = self.call(
            {**self.upload_data(), **self.destination},
            upload=True,
            user=self.normal_user,
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_object_access_does_not_grant_files_field_access(self) -> None:
        """Deny attaching files when a row grant permits only an unrelated field."""
        permissions = [BloomerpPermission.VIEW, BloomerpPermission.ADD]
        policy = PolicyManager.create_policy(
            model_or_content_type=self.CustomerModel,
            field_permissions={"first_name": permissions},
            row_permissions=[
                RowPolicyRuleContent(permissions=permissions, conditions=[])
            ],
        )
        policy.users.add(self.normal_user)
        response = self.call(
            {**self.upload_data(), **self.destination},
            upload=True,
            user=self.normal_user,
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.customer.files.exists())

    def test_field_owned_file_cannot_be_reassigned(self) -> None:
        """Keep the canonical file reference and its owning form field intact."""
        self.CustomerModel._meta.get_field("picture").on_save(
            self.customer, [], [SimpleUploadedFile("picture.txt", b"picture")]
        )
        file = File.objects.get(pk=self.customer.picture[0].pk)
        response = self.call(
            {"file_id": str(file.pk), **self.destination}, user=self.admin_user
        )
        self.assertEqual(response.status_code, 400)
        self.assertIsNotNone(file.field_reference)

    def test_mcp_tools_expose_file_ids_and_portable_destinations(self) -> None:
        """Register both actions with truthful mutation and idempotency annotations."""
        tools = {route.mcp_tool_name: route.mcp for route in router.get_mcp_routes()}
        upload = tools["api_assistant_file_upload"]
        link = tools["api_assistant_file_link"]
        self.assertEqual(
            upload.get_input_schema()["required"], ["filename", "content_base64"]
        )
        self.assertNotIn("file", upload.get_input_schema()["properties"])
        self.assertIn("model_label", link.get_input_schema()["properties"])
        self.assertFalse(upload.read_only_hint)
        self.assertTrue(link.destructive_hint)
        self.assertTrue(link.idempotent_hint)

    def test_file_api_metadata_and_openapi_expose_identifiers(self) -> None:
        """Expose inherited destination IDs and file IDs through OPTIONS and OpenAPI."""
        views = [AssistantFileUploadView, AssistantFileLinkView]
        for view in views:
            with self.subTest(view=view.__name__):
                request = APIRequestFactory().options("/")
                force_authenticate(request, user=self.admin_user)
                response = view.as_view()(request)
                self.assertEqual(response.status_code, 200)
                fields = response.data["actions"]["POST"]
                self.assertIn("object_id", fields)
                self.assertIn("model_label", fields)
                if view is AssistantFileLinkView:
                    self.assertIn("file_id", fields)
                    self.assertTrue(fields["file_id"]["required"])

        schema = SchemaGenerator(patterns=[
            path("files/upload/", AssistantFileUploadView.as_view()),
            path("files/link/", AssistantFileLinkView.as_view()),
        ]).get_schema(request=None, public=True)
        components = schema["components"]["schemas"]
        for endpoint, status in [("upload", "201"), ("link", "200")]:
            with self.subTest(endpoint=endpoint):
                operation = schema["paths"][f"/files/{endpoint}/"]["post"]
                request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
                input_fields = components[request_ref.rsplit("/", 1)[-1]]["properties"]
                self.assertIn("object_id", input_fields)
                if endpoint == "link":
                    self.assertIn("file_id", input_fields)
                response_ref = operation["responses"][status]["content"]["application/json"]["schema"]["$ref"]
                output_fields = components[response_ref.rsplit("/", 1)[-1]]["properties"]
                self.assertIn("file_id", output_fields)
                self.assertIn("object_id", output_fields)
