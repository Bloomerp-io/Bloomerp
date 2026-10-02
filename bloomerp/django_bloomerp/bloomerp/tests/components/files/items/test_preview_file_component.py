from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse, StreamingHttpResponse

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
        return scenarios

    def range_bytes(self, response: HttpResponse | StreamingHttpResponse) -> bool:
        """Check the native media player receives exactly its requested byte range."""
        return b"".join(response.streaming_content) == b"2345"

    def image_bytes(self, response: HttpResponse | StreamingHttpResponse) -> bool:
        """Check image storage bytes are served directly through the authorized route."""
        return b"".join(response.streaming_content) == b"image"
