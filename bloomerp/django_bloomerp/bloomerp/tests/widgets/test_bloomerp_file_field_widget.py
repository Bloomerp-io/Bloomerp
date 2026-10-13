from types import SimpleNamespace
from typing import Any
from uuid import UUID

from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.utils.datastructures import MultiValueDict

from bloomerp.tests.base import BloomerpWidgetTestCase, WidgetOperation, WidgetScenario
from bloomerp.widgets.file_field_widget import BloomerpFileFieldWidget


class TestBloomerpFileFieldWidget(BloomerpWidgetTestCase):
    widget_class = BloomerpFileFieldWidget

    def get_test_scenarios(self) -> list[WidgetScenario[BloomerpFileFieldWidget]]:
        """Cover plain inputs and side-effect-free upload extraction."""
        return [
            WidgetScenario(
                name="retained file opens the shared preview drawer",
                operations=[
                    WidgetOperation(
                        name="render preview link",
                        execute=self.render_preview_link,
                        result_validators=self.preview_link_markup,
                    )
                ],
            ),
            WidgetScenario(
                name="single input replaces old attachment",
                operations=[
                    WidgetOperation(
                        name="extract replacement",
                        execute=self.extract_uploads,
                        result_validators=self.single_replacement,
                    )
                ],
            ),
            WidgetScenario(
                name="multiple input retains old attachments",
                constructor_kwargs={"multiple": True},
                operations=[
                    WidgetOperation(
                        name="extract multiple",
                        execute=self.extract_uploads,
                        result_validators=self.multiple_uploads,
                    ),
                    WidgetOperation(
                        name="render multiple input",
                        execute=self.render_input,
                        result_validators=self.multiple_markup,
                    ),
                ],
            ),
            WidgetScenario(
                name="empty editor explicitly removes attachments",
                operations=[
                    WidgetOperation(
                        name="extract empty",
                        execute=self.extract_empty,
                        result_validators=self.empty_value,
                    )
                ],
            ),
            WidgetScenario(
                name="invalid input rendering has no DB side effects",
                operations=[
                    WidgetOperation(
                        name="render invalid",
                        execute=self.render_invalid,
                        result_validators=self.invalid_markup,
                    )
                ],
            ),
        ]

    def render_preview_link(self, widget: BloomerpFileFieldWidget) -> str:
        """Render an existing file using the widget's template and input context."""
        context = widget.get_context("picture", None, {"id": "id_picture"})
        context["current_files"] = [
            SimpleNamespace(
                pk=UUID("12345678-1234-5678-1234-567812345678"), name="Preview.png"
            )
        ]
        return render_to_string(widget.template_name, context)

    def preview_link_markup(self, result: str) -> bool:
        """Check the retained file loads the existing preview route into the shared drawer."""
        return (
            'bloomerp-open-drawer="bloomerp-general-use-drawer"' in result
            and 'hx-target="#bloomerp-general-use-drawer-body"' in result
            and 'hx-get="' in result
            and "preview_file/12345678-1234-5678-1234-567812345678/" in result
        )

    def extract_uploads(self, widget: BloomerpFileFieldWidget) -> dict[str, Any]:
        """Submit a retained ID and one or two uploads to the input."""
        uploads = [SimpleUploadedFile("a.pdf", b"a")]
        if widget.allow_multiple_selected:
            uploads.append(SimpleUploadedFile("b.pdf", b"b"))
        return widget.value_from_datadict(
            MultiValueDict({"picture__retain": ["old-id"]}),
            MultiValueDict({"picture": uploads}),
            "picture",
        )

    def single_replacement(self, result: dict[str, Any]) -> bool:
        """Check a single upload replaces the old reference."""
        return len(result["uploads"]) == 1 and result["retained"] == []

    def multiple_uploads(self, result: dict[str, Any]) -> bool:
        """Check all uploads and retained controls are extracted."""
        return len(result["uploads"]) == 2 and result["retained"] == ["old-id"]

    def render_input(self, widget: BloomerpFileFieldWidget) -> str:
        """Render the normal multiple file input."""
        return widget.render("picture", None, attrs={"id": "id_picture"})

    def multiple_markup(self, result: str) -> bool:
        """Check multipart input and explicit submission marker."""
        return (
            'type="file"' in result
            and "multiple" in result
            and "picture__present" in result
        )

    def extract_empty(self, widget: BloomerpFileFieldWidget) -> dict[str, Any]:
        """Extract an explicitly empty editor submission."""
        return widget.value_from_datadict({"picture__present": "1"}, {}, "picture")

    def empty_value(self, result: dict[str, Any]) -> bool:
        """Check deselected attachments are absent from the raw value."""
        return result == {"uploads": [], "retained": []}

    def render_invalid(self, widget: BloomerpFileFieldWidget) -> str:
        """Render validation state without querying or deleting an attachment."""
        return widget.render("picture", "untrusted-id", attrs={"aria-invalid": "true"})

    def invalid_markup(self, result: str) -> bool:
        """Check invalid rendering preserves the file input."""
        return 'aria-invalid="true"' in result and 'type="file"' in result
