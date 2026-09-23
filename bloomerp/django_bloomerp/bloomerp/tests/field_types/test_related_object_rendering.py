from types import SimpleNamespace

from django.test import SimpleTestCase

from bloomerp.field_types.utils.render_value_functions import (
    render_foreign_key_dataview_value,
)


class RelatedObject:
    """A related record with a long label and a detail URL."""

    def __str__(self) -> str:
        """Return a long label containing HTML-sensitive text."""
        return "Review <launch> " + "notes " * 20

    def get_absolute_url(self) -> str:
        """Return the destination for the related-record link."""
        return "/related/1/"


class TestRelatedObjectRendering(SimpleTestCase):
    """Related-record cells keep long labels compact and escaped."""

    def test_foreign_key_label_is_shortened(self) -> None:
        """
        Use case: A related object has a long, HTML-sensitive label.
        Expected result: Its data-view link is shortened and escaped.
        """
        # 1. Render a related-object cell.
        record = SimpleNamespace(related=RelatedObject())
        field = SimpleNamespace(field="related")
        markup = str(render_foreign_key_dataview_value(field, record))

        # 2. Verify the link, truncation, and escaping.
        self.assertIn('href="/related/1/"', markup)
        self.assertIn("Review &lt;launch&gt;", markup)
        self.assertIn("…", markup)
        self.assertNotIn("notes " * 20, markup)
