"""Pagination contracts verified against fresh PDFs from the real renderer."""

from io import BytesIO

from django.test import SimpleTestCase
from PyPDF2 import PdfReader

from bloomerp.utils.pdf import generate_pdf


class TestPdfPageBreaks(SimpleTestCase):
    """Check the semantic marker independently of templates and the editor UI."""

    marker = '<div data-document-template-page-break="true"></div>'

    def render_page_text(self, content: str) -> list[str]:
        """Render a new PDF and return normalized text from each physical page."""
        pdf_bytes = generate_pdf(content, include_page_numbers=False)
        return [
            " ".join(page.extract_text().split())
            for page in PdfReader(BytesIO(pdf_bytes)).pages
        ]

    def test_marker_starts_following_content_on_new_page(self) -> None:
        """Place the two neighboring paragraphs on separate physical PDF pages."""
        self.assertEqual(
            self.render_page_text(f"<p>Before</p>{self.marker}<p>After</p>"),
            ["Before", "After"],
        )

    def test_repeated_markers_preserve_page_order(self) -> None:
        """Honor every separated break without leaking editor labels into print."""
        self.assertEqual(
            self.render_page_text(
                f"<p>First</p>{self.marker}<p>Second</p>{self.marker}<p>Third</p>"
            ),
            ["First", "Second", "Third"],
        )

    def test_consecutive_markers_allow_an_explicit_blank_page(self) -> None:
        """Keep consecutive intentional breaks instead of silently discarding one."""
        self.assertEqual(
            self.render_page_text(f"<p>Before</p>{self.marker * 2}<p>After</p>"),
            ["Before", "", "After"],
        )

    def test_trailing_marker_does_not_add_an_unused_page(self) -> None:
        """Avoid an extra final page when nothing follows the last marker."""
        self.assertEqual(self.render_page_text(f"<p>Before</p>{self.marker}"), ["Before"])

    def test_empty_paragraph_after_marker_remains_on_following_page(self) -> None:
        """Keep the editor's empty editable paragraph after a trailing insertion."""
        self.assertEqual(
            self.render_page_text(f"<p>Before</p>{self.marker}<p></p>"),
            ["Before", ""],
        )

    def test_table_following_marker_starts_on_new_page(self) -> None:
        """Keep a following table wholly after the explicit page boundary."""
        self.assertEqual(
            self.render_page_text(
                f"<p>Before</p>{self.marker}<table><tr><td>After</td></tr></table>"
            ),
            ["Before", "After"],
        )

    def test_marker_inside_table_cell_starts_following_content_on_new_page(self) -> None:
        """Honor a break imported into a table cell as well as top-level content."""
        self.assertEqual(
            self.render_page_text(
                f"<table><tr><td><p>Before</p>{self.marker}<p>After</p></td></tr></table>"
            ),
            ["Before", "After"],
        )

    def test_table_cell_marker_preserves_neighboring_cell_content(self) -> None:
        """Split the marked cell without moving or dropping the adjacent cell."""
        self.assertEqual(
            self.render_page_text(
                f"<table><tr><td><p>Before</p>{self.marker}<p>After</p></td>"
                "<td>Other</td></tr></table>"
            ),
            ["Before Other", "After"],
        )

    def test_marker_remains_block_level_under_generic_div_styling(self) -> None:
        """Preserve explicit pagination when ordinary template divs are inline."""
        pdf_bytes = generate_pdf(
            f"<p>Before</p>{self.marker}<p>After</p>",
            css_content="div { display: inline; }",
            include_page_numbers=False,
        )
        self.assertEqual(
            [page.extract_text().strip() for page in PdfReader(BytesIO(pdf_bytes)).pages],
            ["Before", "After"],
        )

    def test_ordinary_html_does_not_gain_a_page_break(self) -> None:
        """Leave ordinary divs and non-matching marker attributes in normal flow."""
        self.assertEqual(
            self.render_page_text(
                '<p>Before</p><div></div>'
                '<div data-document-template-page-break="false"></div>'
                '<span data-document-template-page-break="true"></span><p>After</p>'
            ),
            ["Before After"],
        )

    def test_default_footer_still_numbers_generated_pages(self) -> None:
        """Preserve default page numbering when a semantic break adds a page."""
        pdf_bytes = generate_pdf(f"<p>Before</p>{self.marker}<p>After</p>")
        pages = [
            " ".join(page.extract_text().split())
            for page in PdfReader(BytesIO(pdf_bytes)).pages
        ]
        self.assertEqual(pages, ["Before Page 1 of 2", "After Page 2 of 2"])
