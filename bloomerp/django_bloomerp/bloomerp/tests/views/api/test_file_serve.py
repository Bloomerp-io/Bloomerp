"""File-byte serving authorization and safe response headers."""

from django.core.files.uploadedfile import SimpleUploadedFile

from bloomerp.models import FileNode
from bloomerp.tests.base import BloomerpAPIViewTestCase, ExpectedResult, RequestScenario


class TestFileServe(BloomerpAPIViewTestCase):
    """Exercise private draft serving through the real registered endpoint."""

    view_name = "api_files_serve"
    auto_create_customers = False

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover uploader/admin access, anonymous denial, and malformed identifiers."""
        file = FileNode.objects.create(
            kind="FILE",
            content=SimpleUploadedFile("draft.png", b"image"),
            created_by=self.normal_user,
        )
        query = {"file_id": str(file.pk)}
        return [
            RequestScenario(
                name="Uploader can preview",
                user=self.normal_user,
                query_params=query,
                expected=ExpectedResult(
                    response_validators=[
                        self.header_equals("Cache-Control", "private, no-store"),
                        self.header_equals("X-Content-Type-Options", "nosniff"),
                    ]
                ),
            ),
            RequestScenario(
                name="Admin can preview", user=self.admin_user, query_params=query
            ),
            RequestScenario(
                name="Anonymous cannot preview",
                query_params=query,
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="Invalid identifier",
                query_params={"file_id": "bad"},
                expected=ExpectedResult(status_code=400),
            ),
        ]
