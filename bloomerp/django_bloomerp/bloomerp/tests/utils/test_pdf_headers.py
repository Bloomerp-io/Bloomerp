"""Exercise physical header layout with the real WeasyPrint layout engine."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase
from PIL import Image, ImageDraw
from weasyprint import HTML
from weasyprint.document import Document

from bloomerp.utils.pdf import generate_pdf


class PdfHeaderLayoutTests(SimpleTestCase):
    """Keep image headers within page margins without overlapping body content."""

    def render_header(self, include_header: bool = True, **options: object) -> Document:
        """Render a synthetic text/image banner without requiring PDF serialization."""
        documents: list[Document] = []

        def capture_layout(html_document: HTML) -> bytes:
            """Capture actual page boxes at the serialization boundary."""
            documents.append(html_document.render())
            return b"%PDF-layout-test"

        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "header.png"
            image = Image.new("RGB", (1600, 200), "white")
            ImageDraw.Draw(image).text((40, 40), "HEADER TEXT AND LOGO", fill="black")
            image.save(image_path)
            with patch.object(HTML, "write_pdf", capture_layout):
                generate_pdf(
                    '<p id="body-marker">BODY START</p><div style="break-before: page">NEXT PAGE</div>',
                    header_url=str(image_path) if include_header else None,
                    **options,
                )
        return documents[0]

    def assert_header_geometry(
        self, document: Document, left: float, top: float, width: float, height: float
    ) -> None:
        """Check repeated headers in CSS pixels and first-page body separation."""
        self.assertEqual(len(document.pages), 2)
        for page in document.pages:
            images = [box for box in page._page_box.descendants() if box.element_tag == "img"]
            self.assertEqual(len(images), 1)
            image = images[0]
            self.assertAlmostEqual(image.position_x, left * 96, places=4)
            self.assertAlmostEqual(image.position_y, top * 96, places=4)
            self.assertAlmostEqual(image.width, width * 96, places=4)
            self.assertAlmostEqual(image.height, height * 96, places=4)
            self.assertLessEqual(image.position_x + image.width, page.width + 0.001)
            self.assertGreaterEqual(image.position_y, 0)
            bodies = [
                box for box in page._page_box.descendants()
                if box.element is not None and box.element.get("id") == "body-marker"
            ]
            for body in bodies:
                self.assertLessEqual(image.position_y + image.height, body.position_y)

    def test_header_uses_inches_instead_of_intrinsic_pixels(self) -> None:
        """A high-resolution banner honors a half-inch configured height."""
        self.assert_header_geometry(self.render_header(header_height=0.5), 1, 0.5, 4, 0.5)

    def test_wide_header_fits_each_page_size_and_orientation(self) -> None:
        """Cap width proportionally using the configured physical page dimensions."""
        for size, portrait_width, landscape_width in (
            ("A4", 210 / 25.4, 297 / 25.4),
            ("A3", 297 / 25.4, 420 / 25.4),
            ("Letter", 8.5, 11),
        ):
            for landscape, page_width in ((False, portrait_width), (True, landscape_width)):
                with self.subTest(size=size, landscape=landscape):
                    width = min(16, page_width - 2)
                    document = self.render_header(
                        header_height=2, page_size=size, is_landscape=landscape
                    )
                    self.assert_header_geometry(document, 1, 0.5, width, width / 8)

    def test_header_margins_are_independent_of_body_margins(self) -> None:
        """Honor asymmetric header margins and reserve the bottom gap."""
        document = self.render_header(
            page_size="letter", page_margin=0.25, header_height=2,
            header_margin_left=0.5, header_margin_right=1.5,
            header_margin_top=0.25, header_margin_bottom=0.5,
        )
        self.assert_header_geometry(document, 0.5, 0.25, 6.5, 6.5 / 8)
        body = document.pages[0]._page_box.children[0]
        self.assertGreaterEqual(body.position_y, (0.25 + 6.5 / 8 + 0.5) * 96)

    def test_zero_header_margins_allow_full_page_width(self) -> None:
        """Allow edge-aligned banners without clipping their right edge."""
        document = self.render_header(
            page_size="letter", header_height=2,
            header_margin_left=0, header_margin_right=0, header_margin_top=0,
        )
        self.assert_header_geometry(document, 0, 0, 8.5, 8.5 / 8)

    def test_document_without_header_preserves_body_margin(self) -> None:
        """Do not reserve header space when no header image was selected."""
        document = self.render_header(include_header=False, page_margin=0.75)
        self.assertEqual(len(document.pages), 2)
        for page in document.pages:
            self.assertFalse(any(
                box.element_tag == "img" for box in page._page_box.descendants()
            ))
            self.assertAlmostEqual(page._page_box.children[0].position_y, 0.75 * 96)
