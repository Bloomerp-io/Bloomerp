from types import SimpleNamespace
from uuid import UUID

from django.urls import reverse

from bloomerp.tests.base import (
    BloomerpWidgetTestCase,
    WidgetOperation,
    WidgetScenario,
)
from bloomerp.widgets.object_files_widget import ObjectFilesWidget


class TestObjectFilesWidget(BloomerpWidgetTestCase):
    widget_class = ObjectFilesWidget

    def get_test_scenarios(self) -> list[WidgetScenario[ObjectFilesWidget]]:
        """Cover existing-file navigation into the shared preview drawer."""
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
            )
        ]

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
