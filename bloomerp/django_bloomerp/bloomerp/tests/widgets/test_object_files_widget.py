from types import SimpleNamespace
from uuid import UUID

from django import forms
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils.datastructures import MultiValueDict

from bloomerp.form_fields.files_relation_field import FilesRelationField
from bloomerp.tests.base import (
    BloomerpWidgetTestCase,
    WidgetOperation,
    WidgetScenario,
)
from bloomerp.widgets.object_files_widget import ObjectFilesWidget


class TestObjectFilesWidget(BloomerpWidgetTestCase):
    widget_class = ObjectFilesWidget

    def get_test_scenarios(self) -> list[WidgetScenario[ObjectFilesWidget]]:
        """Cover saved-file previews and upload rendering after failed validation."""
        return [
            WidgetScenario(
                name="existing files open the preview drawer",
                operations=[
                    WidgetOperation(
                        name="render file link",
                        execute=self.render_file_link,
                        result_validators=self.opens_preview_drawer,
                    )
                ],
            ),
            WidgetScenario(
                name="invalid bound form does not preview unsaved uploads",
                operations=[
                    WidgetOperation(
                        name="render bound uploads after validation fails",
                        execute=self.render_invalid_form,
                        result_validators=self.upload_input_without_preview,
                    )
                ],
            ),
            WidgetScenario(
                name="mixed values preview only saved files",
                operations=[
                    WidgetOperation(
                        name="render saved file alongside upload",
                        execute=self.render_mixed_files,
                        result_validators=self.opens_preview_drawer,
                    )
                ],
            ),
        ]

    def render_invalid_form(self, widget: ObjectFilesWidget) -> str:
        """Redisplay uploaded attachments when another bound form field is invalid."""
        upload = SimpleUploadedFile("receipt.pdf", b"receipt")
        form = forms.Form(data={}, files=MultiValueDict({"files": [upload]}))
        form.fields["description"] = forms.CharField(required=True)
        form.fields["files"] = FilesRelationField(required=False, widget=widget)
        self.assertFalse(form.is_valid())
        self.assertEqual(form.cleaned_data["files"].files, [upload])
        return str(form["files"])

    def upload_input_without_preview(self, result: str) -> bool:
        """Check invalid uploads leave a usable input without a nonexistent preview."""
        return (
            'type="file"' in result
            and 'name="files"' in result
            and 'multiple' in result
            and 'hx-get=' not in result
        )

    def render_mixed_files(self, widget: ObjectFilesWidget) -> str:
        """Keep saved-file preview links when raw values also include an upload."""
        return widget.render(
            "files",
            [
                SimpleNamespace(
                    pk=UUID("12345678-1234-5678-1234-567812345678"),
                    name="Report.pdf",
                ),
                SimpleUploadedFile("receipt.pdf", b"receipt"),
            ],
        )

    def render_file_link(self, widget: ObjectFilesWidget) -> str:
        """Render one listed file without querying storage or the database."""
        return widget.render(
            "files",
            [
                SimpleNamespace(
                    pk=UUID("12345678-1234-5678-1234-567812345678"),
                    name="Report.pdf",
                    size_str="40.38 KB",
                    url="/media/report.pdf",
                )
            ],
        )

    def opens_preview_drawer(self, result: str) -> bool:
        """Check file links request the preview component and open the shared drawer."""
        preview_url = reverse(
            "components_preview_file",
            kwargs={"file_id": "12345678-1234-5678-1234-567812345678"},
        )
        return (
            f'href="{preview_url}"' in result
            and f'hx-get="{preview_url}"' in result
            and 'hx-target="#bloomerp-general-use-drawer-body"' in result
            and 'bloomerp-open-drawer="bloomerp-general-use-drawer"' in result
            and 'target="_blank"' not in result
            and "/media/report.pdf" not in result
        )
