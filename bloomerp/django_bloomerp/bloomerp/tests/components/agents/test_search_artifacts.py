"""Routed scenarios for permission-aware attachment discovery and upload."""

from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import override_settings

from bloomerp.models.files.file_node import FileNode
from bloomerp.modules.definition import ModuleConfig
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestSearchArtifacts(BloomerpComponentTestCase):
    """Exercise real registry dispatch without exposing unavailable source metadata."""

    view_name = "components_search_artifacts"

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover categories, bounded source search and method/authentication gates."""
        owner = get_user_model().objects.create_user(
            username="attachment-search-owner", is_superuser=True
        )
        other = get_user_model().objects.create_user(username="attachment-search-other")
        FileNode.objects.create(
            name="private-invoice.pdf", content=SimpleUploadedFile("invoice.pdf", b"private"), kind="FILE"
        )
        modules = {
            "finance": ModuleConfig(
                id="finance",
                name="Finance",
                code="finance",
                description="Revenue and invoices",
            )
        }
        self.enterContext(
            patch(
                "bloomerp.modules.definition.module_registry.get_enabled",
                return_value=modules,
            )
        )
        self.enterContext(
            patch(
                "bloomerp.modules.definition.module_registry.get_models_for_module",
                return_value=[FileNode],
            )
        )
        return [
            RequestScenario(
                name="Only attachable categories",
                user=owner,
                expected=ExpectedResult(response_validators=self.categories),
            ),
            RequestScenario(
                name="Readable file",
                user=owner,
                query_params={"type": "file", "q": "invoice"},
                expected=ExpectedResult(response_validators=self.signed_file),
            ),
            RequestScenario(
                name="Unreadable files hidden",
                user=other,
                query_params={"type": "file"},
                expected=ExpectedResult(response_validators=self.empty),
            ),
            RequestScenario(
                name="Module search",
                user=owner,
                query_params={"type": "module", "q": "revenue"},
                expected=ExpectedResult(response_validators=self.module),
            ),
            RequestScenario(
                name="Unreadable modules hidden",
                user=other,
                query_params={"type": "module"},
                expected=ExpectedResult(response_validators=self.empty),
            ),
            RequestScenario(
                name="Unknown type",
                user=owner,
                query_params={"type": "missing"},
                expected=ExpectedResult(status_code=400),
            ),
            RequestScenario(
                name="Invalid file cursor",
                user=owner,
                query_params={"type": "file", "cursor": "bad"},
                expected=ExpectedResult(status_code=400),
            ),
            RequestScenario(
                name="Invalid page bound",
                user=owner,
                query_params={"type": "file", "limit": 0},
                expected=ExpectedResult(status_code=400),
            ),
            RequestScenario(name="Anonymous", expected=ExpectedResult(status_code=302)),
            RequestScenario(
                name="Search is read-only",
                user=owner,
                method="POST",
                expected=ExpectedResult(status_code=405),
            ),
        ]

    def categories(self, response: HttpResponse) -> bool:
        """Keep visualization-only types out of manual attachment discovery."""
        return {item["key"] for item in response.json()["types"]} == {
            "file",
            "module",
            "model",
            "object",
        }

    def signed_file(self, response: HttpResponse) -> bool:
        """Return source metadata with a signed token and never a storage URL."""
        items = response.json()["items"]
        return (
            len(items) == 1
            and items[0]["title"] == "private-invoice.pdf"
            and bool(items[0]["token"])
            and "url" not in items[0]
        )

    def module(self, response: HttpResponse) -> bool:
        """Find modules by their descriptions as well as their labels."""
        return [item["title"] for item in response.json()["items"]] == ["Finance"]

    def empty(self, response: HttpResponse) -> bool:
        """Verify inaccessible sources do not leak through search metadata."""
        return response.json()["items"] == []


class TestUploadArtifact(BloomerpComponentTestCase):
    """Exercise uploads through registered handlers and existing file permissions."""

    view_name = "components_upload_artifact"

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Prepare isolated file storage for successful and rejected upload scenarios."""
        storage = self.enterContext(TemporaryDirectory())
        self.enterContext(
            override_settings(MEDIA_ROOT=storage, BLOOMERP_AGENT_UPLOAD_MAX_BYTES=32)
        )
        owner = get_user_model().objects.create_user(
            username="attachment-upload-owner", is_superuser=True
        )
        other = get_user_model().objects.create_user(username="attachment-upload-other")
        return [
            RequestScenario(
                name="Upload to library",
                user=owner,
                method="POST",
                prepare=self.pdf,
                expected=ExpectedResult(response_validators=self.saved),
            ),
            RequestScenario(
                name="Upload requires file permission",
                user=other,
                method="POST",
                prepare=self.pdf,
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="Upload size bound",
                user=owner,
                method="POST",
                prepare=self.large,
                expected=ExpectedResult(status_code=400),
            ),
            RequestScenario(
                name="Module has no upload handler",
                user=owner,
                method="POST",
                prepare=self.module_file,
                expected=ExpectedResult(status_code=400),
            ),
            RequestScenario(
                name="Missing file",
                user=owner,
                method="POST",
                data={"type": "file"},
                expected=ExpectedResult(status_code=400),
            ),
            RequestScenario(
                name="Upload needs authentication",
                method="POST",
                expected=ExpectedResult(status_code=302),
            ),
        ]

    def pdf(self, scenario: RequestScenario) -> None:
        """Create a fresh multipart stream for each upload scenario."""
        scenario.data = {
            "type": "file",
            "file": SimpleUploadedFile(
                "invoice.pdf", b"%PDF-1.4 sample", content_type="application/pdf"
            ),
        }

    def large(self, scenario: RequestScenario) -> None:
        """Exceed the configured byte limit before storage is created."""
        scenario.data = {
            "type": "file",
            "file": SimpleUploadedFile("large.pdf", b"x" * 33),
        }

    def module_file(self, scenario: RequestScenario) -> None:
        """Try to upload through a searchable but non-uploadable type."""
        self.pdf(scenario)
        scenario.data["type"] = "module"

    def saved(self, response: HttpResponse) -> bool:
        """Verify upload persistence and the returned selection contract."""
        return (
            response.json()["title"] == "invoice.pdf"
            and bool(response.json()["token"])
            and FileNode.objects.filter(name="invoice.pdf", kind="FILE").exists()
        )
