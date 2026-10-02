from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse, StreamingHttpResponse
from django.test import AsyncRequestFactory, RequestFactory

from bloomerp.components.files.items.preview import _media_response, preview_file
from bloomerp.models import File
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
        file = File.objects.create(
            file=SimpleUploadedFile("widget.png", b"image"), persisted=True
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
            preview = File.objects.create(
                file=SimpleUploadedFile(name, content), persisted=True
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
        pdf = File.objects.create(
            file=SimpleUploadedFile("range.pdf", b"0123456789"), persisted=True
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
        return scenarios

    def test_pdf_preview_does_not_read_storage(self) -> None:
        """
        Use case: A large PDF is opened in the drawer.
        Expected result: Rendering its iframe never reads or Base64-encodes its contents.
        """
        # 1. Make every attempted storage read fail while rendering the preview.
        file = File(file=ContentFile(b"pdf", name="large.pdf"), name="Large PDF")
        request = RequestFactory().get("/")
        request.user = self.admin_user
        with patch.object(
            file.file, "open", side_effect=AssertionError("Unexpected read")
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
        file = File(file=ContentFile(data, name="large.pdf"))
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
