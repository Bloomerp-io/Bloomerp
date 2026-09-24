from types import SimpleNamespace

from django.test import SimpleTestCase
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

from bloomerp.field_types.utils.render_value_functions import (
    render_foreign_key_dataview_value,
    render_m2m_dataview_value,
)


class RelatedObject:
    """A related record with a long label and a detail URL."""

    def __str__(self) -> str:
        """Return a long label containing HTML-sensitive text."""
        return "Review <launch> " + "notes " * 20

    def get_absolute_url(self) -> str:
        """Return the destination for the related-record link."""
        return "/related/1/"


class RelatedManager:
    """Provide the related-record operations used by the cell renderer."""

    def count(self) -> int:
        """Report one related record."""
        return 1

    def all(self) -> list[RelatedObject]:
        """Return the records available for rendering."""
        return [RelatedObject()]


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

    def test_safe_link_does_not_break_table_cell_attributes(self) -> None:
        """Escape link markup when it is repeated in a data attribute."""
        markup = render_to_string(
            "inclusion_tags/dataview_value.html",
            {
                "value": mark_safe('<a href="/related/1/">Related</a>'),
                "object": SimpleNamespace(pk=1),
                "object_string": "Record",
                "application_field": SimpleNamespace(field="related"),
                "application_field_id": 1,
            },
        )

        self.assertIn('data-value="&lt;a href=&quot;/related/1/&quot;&gt;Related&lt;/a&gt;"', markup)
        self.assertIn('<a href="/related/1/">Related</a>', markup)
        self.assertNotIn('data-value="<a href=', markup)

    def test_many_to_many_badge_escapes_label(self) -> None:
        """Render each related label as escaped text inside a safe badge."""
        record = SimpleNamespace(related=RelatedManager())
        field = SimpleNamespace(field="related")

        markup = str(render_m2m_dataview_value(field, record))

        self.assertIn('href="/related/1/"', markup)
        self.assertIn("Review &lt;launch&gt;", markup)
        self.assertNotIn("<launch>", markup)
