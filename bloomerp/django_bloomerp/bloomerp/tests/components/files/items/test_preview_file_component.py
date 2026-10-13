from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse, StreamingHttpResponse
from django.test import AsyncRequestFactory, RequestFactory

from bloomerp.components.files.items.preview import _media_response, preview_file
from bloomerp.models.files.file_node import FileNode, _can_view_file_node
from bloomerp.models.files.file_reference import FileReference
from bloomerp.permissions.definition import RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestPreviewFileComponent(BloomerpComponentTestCase):
    """Tests function `preview_file` from `bloomerp/components/files/items/preview.py`."""

    view_name = "components_preview_file"

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Check the widget's GET preview route accepts a file identifier."""
        file = FileNode.objects.create(
            content=SimpleUploadedFile("widget.png", b"image"), kind="FILE", name="widget.png"
        )
        scenarios = [
            RequestScenario(
                name="File identifier renders an image preview",
                user=self.admin_user,
                view_kwargs={"file_id": str(file.pk)},
                expected=ExpectedResult(response_validators=self.contains_text("<img")),
            )
        ]

        for name, content, expected in [
            ("movie.mp4", b"0123456789", "<video"),
            ("sound.mp3", b"audio", "<audio"),
            ("table.csv", b"Name,Value\nExample,42", "<table"),
            ("notes.html", b"<script>alert(1)</script>", "&lt;script&gt;"),
            ("book.xlsx", b"unsupported", "Preview unavailable"),
        ]:
            preview = FileNode.objects.create(
                content=SimpleUploadedFile(name, content), kind="FILE", name=name
            )
            scenarios.append(
                RequestScenario(
                    name=f"Preview {name}",
                    user=self.admin_user,
                    view_kwargs={"file_id": str(preview.pk)},
                    expected=ExpectedResult(
                        response_validators=self.contains_text(expected)
                    ),
                )
            )
            if name == "movie.mp4":
                scenarios.append(
                    RequestScenario(
                        name="Video byte range supports seeking",
                        user=self.admin_user,
                        view_kwargs={"file_id": str(preview.pk)},
                        query_params={"raw": "1"},
                        headers={"Range": "bytes=2-5"},
                        expected=ExpectedResult(
                            status_code=206,
                            response_validators=[
                                self.header_equals("Content-Range", "bytes 2-5/10"),
                                self.range_bytes,
                            ],
                        ),
                    )
                )
                scenarios.append(
                    RequestScenario(
                        name="Private media denies users without access",
                        user=self.normal_user,
                        view_kwargs={"file_id": str(preview.pk)},
                        query_params={"raw": "1"},
                        expected=ExpectedResult(status_code=403),
                    )
                )
        scenarios.append(
            RequestScenario(
                name="PNG bytes load without a public media route",
                user=self.admin_user,
                view_kwargs={"file_id": str(file.pk)},
                query_params={"raw": "1"},
                expected=ExpectedResult(
                    response_validators=[
                        self.header_equals("Content-Type", "image/png"),
                        self.image_bytes,
                    ]
                ),
            )
        )
        pdf = FileNode.objects.create(
            content=SimpleUploadedFile("range.pdf", b"0123456789"), kind="FILE", name="range.pdf"
        )
        scenarios.append(
            RequestScenario(
                name="PDF viewer streams its requested byte range",
                user=self.admin_user,
                view_kwargs={"file_id": str(pdf.pk)},
                query_params={"raw": "1"},
                headers={"Range": "bytes=2-5"},
                expected=ExpectedResult(
                    status_code=206,
                    response_validators=[
                        self.header_equals("Content-Type", "application/pdf"),
                        self.header_equals("X-Frame-Options", "SAMEORIGIN"),
                        self.range_bytes,
                    ],
                ),
            )
        )
        folder = FileNode.objects.create(name="Folder", kind="FOLDER")
        for query in ({}, {"raw": "1"}, {"download": "1"}):
            scenarios.extend([
                RequestScenario(
                    name=f"Folders cannot be previewed or downloaded: {query}",
                    user=self.admin_user,
                    view_kwargs={"file_id": str(folder.pk)},
                    query_params=query,
                    expected=ExpectedResult(status_code=404),
                ),
                RequestScenario(
                    name=f"Unreadable files deny every content route: {query}",
                    user=self.normal_user,
                    view_kwargs={"file_id": str(file.pk)},
                    query_params=query,
                    expected=ExpectedResult(status_code=403),
                ),
            ])
        scenarios.extend([
            RequestScenario(
                name="Download returns original bytes with the display filename",
                user=self.admin_user,
                view_kwargs={"file_id": str(pdf.pk)},
                query_params={"download": "1"},
                expected=ExpectedResult(response_validators=[
                    lambda response: b"".join(response.streaming_content) == b"0123456789",
                    lambda response: response["Content-Disposition"] == 'attachment; filename="range.pdf"',
                ]),
            ),
            RequestScenario(
                name="Unsatisfiable byte range returns total content size",
                user=self.admin_user,
                view_kwargs={"file_id": str(pdf.pk)},
                query_params={"raw": "1"},
                headers={"Range": "bytes=20-30"},
                expected=ExpectedResult(status_code=416, response_validators=[
                    lambda response: response["Content-Range"] == "bytes */10",
                ]),
            ),
            RequestScenario(
                name="Malformed node identifier is not a server error",
                user=self.admin_user,
                view_kwargs={"file_id": "invalid"},
                expected=ExpectedResult(status_code=404),
            ),
            RequestScenario(
                name="Anonymous previews require login",
                view_kwargs={"file_id": str(pdf.pk)},
                expected=ExpectedResult(status_code=302),
            ),
        ])
        customer = self.create_customer("Preview", "Owner", 30)
        linked = FileNode.objects.create(
            name="Linked.pdf", kind="FILE", content=SimpleUploadedFile("linked.pdf", b"pdf")
        )
        FileReference.objects.create(file=linked, content_object=customer)
        self.customer = customer
        owned = FileNode.objects.create(
            name="Own upload.pdf", kind="FILE",
            content=SimpleUploadedFile("own.pdf", b"pdf"), created_by=self.normal_user,
        )
        scenarios.extend([
            RequestScenario(
                name="Uploader can preview an unreferenced node",
                user=self.normal_user,
                view_kwargs={"file_id": str(owned.pk)},
                expected=ExpectedResult(response_validators=lambda response: "<iframe" in response.content.decode()),
            ),
            RequestScenario(
                name="A reference alone does not grant its target's files permission",
                user=self.normal_user,
                view_kwargs={"file_id": str(linked.pk)},
                expected=ExpectedResult(status_code=403),
            ),
        ])
        scenarios.append(RequestScenario(
            name="Object files permission allows a referenced node preview",
            user=self.normal_user,
            view_kwargs={"file_id": str(linked.pk)},
            prepare=self.grant_files_access,
            expected=ExpectedResult(response_validators=lambda response: "<iframe" in response.content.decode()),
        ))
        return scenarios

    def grant_files_access(self, scenario: RequestScenario) -> None:
        """Grant the normal user read access to customer files through stored policy."""
        policy = PolicyManager.create_policy(
            model_or_content_type=self.CustomerModel,
            field_permissions={"files": ["view"]},
            row_permissions=[RowPolicyRuleContent(permissions=["view"], conditions=[])],
        )
        policy.users.add(self.normal_user)

    def test_preview_action_and_cached_metadata(self) -> None:
        """Use node permissions for the View action and cached facts for byte ranges."""
        file = FileNode.objects.create(
            name="Renamed", kind="FILE", content=SimpleUploadedFile("original.pdf", b"0123456789")
        )
        request = RequestFactory().get("/?raw=1", HTTP_RANGE="bytes=2-5")
        request.user = self.admin_user
        self.assertTrue(_can_view_file_node(request, file))
        with patch.object(file.content.storage, "size", side_effect=AssertionError("Unexpected stat")):
            response = preview_file(request, file)
            self.assertEqual(response["Content-Type"], "application/pdf")
            self.assertEqual(b"".join(response.streaming_content), b"2345")
        request.user = self.normal_user
        self.assertFalse(_can_view_file_node(request, file))

    def test_pdf_preview_does_not_read_storage(self) -> None:
        """
        Use case: A large PDF is opened in the drawer.
        Expected result: Rendering its iframe never reads or Base64-encodes its contents.
        """
        # 1. Make every attempted storage read fail while rendering the preview.
        file = FileNode(content=ContentFile(b"pdf", name="large.pdf"), name="Large PDF", kind="FILE")
        request = RequestFactory().get("/")
        request.user = self.admin_user
        with patch.object(
            file.content, "open", side_effect=AssertionError("Unexpected read")
        ):
            response = preview_file(request, file)
        # 2. Only the authorized streaming endpoint appears in the small HTML fragment.
        self.assertContains(response, "?raw=1")
        self.assertNotContains(response, "data:application/pdf")

    def test_pdf_stream_is_async_under_asgi(self) -> None:
        """
        Use case: Django serves a PDF from the deployed ASGI application.
        Expected result: Its iterator stays asynchronous and reads bounded chunks.
        """
        # 1. Request a PDF spanning multiple chunks without touching the database.
        data = b"p" * (128 * 1024 + 1)
        file = FileNode(content=ContentFile(data, name="large.pdf"), kind="FILE")
        response = _media_response(AsyncRequestFactory().get("/"), file)
        self.assertTrue(response.is_async)
        # 2. Consume the async stream without Django adapting it into a buffered list.
        async_to_sync(self.assert_streamed_pdf)(response, data)

    async def assert_streamed_pdf(
        self, response: StreamingHttpResponse, expected: bytes
    ) -> None:
        """Check PDF chunks have bounded size and preserve the original bytes."""
        chunks = [chunk async for chunk in response.streaming_content]
        self.assertEqual(len(chunks), 3)
        self.assertTrue(all(len(chunk) <= 64 * 1024 for chunk in chunks))
        self.assertEqual(b"".join(chunks), expected)

    def range_bytes(self, response: HttpResponse | StreamingHttpResponse) -> bool:
        """Check the native media player receives exactly its requested byte range."""
        return b"".join(response.streaming_content) == b"2345"

    def image_bytes(self, response: HttpResponse | StreamingHttpResponse) -> bool:
        """Check image storage bytes are served directly through the authorized route."""
        return b"".join(response.streaming_content) == b"image"
