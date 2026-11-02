"""Render validated signing values onto a separate copy of the original PDF."""

from collections.abc import Mapping, Sequence
from io import BytesIO
from pathlib import Path

import reportlab
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from rest_framework.exceptions import ValidationError

from bloomerp.models.document_signing import SignatureRequestField
from bloomerp.models.document_signing.definition import (
    DrawnSignature,
    SignatureFieldType,
    validate_drawn_signature,
)
from bloomerp.models.files.file_node import FileNode


def read_pdf_content(file: FileNode) -> bytes:
    """Read immutable stored PDF bytes and report unavailable storage without exposing paths."""
    try:
        with file.content.open("rb") as stream:
            return stream.read()
    except OSError as error:
        raise ValidationError(
            "The original PDF is unavailable. Try again later."
        ) from error


def signing_pdf_reader(content: bytes) -> PdfReader:
    """Reject unreadable or encrypted documents before any signing records are changed."""
    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted or not reader.pages:
            raise ValidationError("Use an unencrypted PDF with at least one page.")
        return reader
    except (PdfReadError, ValueError) as error:
        raise ValidationError("The document could not be read as a PDF.") from error


def signing_font(italic: bool = False) -> str:
    """Use the bundled Unicode font for names, initials and retained legacy text."""
    name = "BloomerpSigningItalic" if italic else "BloomerpSigning"
    if name not in pdfmetrics.getRegisteredFontNames():
        filename = "VeraIt.ttf" if italic else "Vera.ttf"
        pdfmetrics.registerFont(
            TTFont(name, str(Path(reportlab.__file__).parent / "fonts" / filename))
        )
    return name


def draw_signing_value(
    canvas: Canvas,
    field: SignatureRequestField,
    value: str | bool | DrawnSignature,
    page_width: float,
    page_height: float,
) -> None:
    """Fit one validated value into its normalized rectangle without truncating accepted text."""
    x, width = float(field.x) * page_width, float(field.width) * page_width
    height = float(field.height) * page_height
    y = page_height - float(field.y) * page_height - height
    canvas.setFillColorRGB(0.08, 0.1, 0.16)
    canvas.setStrokeColorRGB(0.08, 0.1, 0.16)
    if field.field_type == SignatureFieldType.SIGNATURE and isinstance(value, dict):
        drawing = validate_drawn_signature(value)
        scale = min(max(0.1, width - 4) / 1000, max(0.1, height - 4) / 300)
        ink_width, ink_height = 1000 * scale, 300 * scale
        left, bottom = x + (width - ink_width) / 2, y + (height - ink_height) / 2
        canvas.saveState()
        canvas.setLineWidth(max(0.25, 3 * scale))
        canvas.setLineCap(1)
        canvas.setLineJoin(1)
        for stroke in drawing["strokes"]:
            path = canvas.beginPath()
            path.moveTo(
                left + stroke[0][0] * ink_width,
                bottom + (1 - stroke[0][1]) * ink_height,
            )
            for horizontal, vertical in stroke[1:]:
                path.lineTo(
                    left + horizontal * ink_width, bottom + (1 - vertical) * ink_height
                )
            canvas.drawPath(path)
        canvas.restoreState()
        return
    if field.field_type == SignatureFieldType.CHECKBOX:
        size = min(width, height) * 0.75
        left, bottom = x + (width - size) / 2, y + (height - size) / 2
        canvas.rect(left, bottom, size, size)
        if value:
            path = canvas.beginPath()
            path.moveTo(left + size * 0.18, bottom + size * 0.5)
            path.lineTo(left + size * 0.42, bottom + size * 0.2)
            path.lineTo(left + size * 0.85, bottom + size * 0.85)
            canvas.drawPath(path)
        return
    signature = field.field_type in {
        SignatureFieldType.SIGNATURE,
        SignatureFieldType.INITIALS,
    }
    font = signing_font(italic=signature)
    size = min(18 if signature else 12, max(1, height - 4) / 1.2)
    lines: list[str] = []
    while size >= 4:
        lines = simpleSplit(str(value), font, size, max(1, width - 4))
        if len(lines) * size * 1.2 <= height - 2 and all(
            pdfmetrics.stringWidth(line, font, size) <= width - 4 for line in lines
        ):
            break
        size -= 0.5
    else:
        raise ValidationError(
            f"{field.settings.get('label') or field.get_field_type_display()}: this value does not fit its PDF field. Shorten it or enlarge the field in the preparation."
        )
    canvas.setFont(font, size)
    baseline = y + height - size - 2
    for line in lines:
        canvas.drawString(x + 2, baseline, line)
        baseline -= size * 1.2


def render_signed_pdf(
    content: bytes,
    fields: Sequence[SignatureRequestField],
    values: Mapping[str, str | bool | DrawnSignature | None],
) -> bytes:
    """Preserve the source document while flattening signed values into rotated/cropped pages."""
    reader = signing_pdf_reader(content)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    pages: dict[int, list[SignatureRequestField]] = {}
    for field in fields:
        if field.page_number > len(writer.pages):
            raise ValidationError("A signing field refers to a page outside the PDF.")
        pages.setdefault(field.page_number, []).append(field)
    for number, placements in pages.items():
        page = writer.pages[number - 1]
        page.transfer_rotation_to_content()
        crop = page.cropbox
        buffer = BytesIO()
        canvas = Canvas(buffer, pagesize=(float(crop.width), float(crop.height)))
        for field in placements:
            value = values.get(str(field.pk))
            if value is not None and value != "":
                draw_signing_value(
                    canvas, field, value, float(crop.width), float(crop.height)
                )
        canvas.showPage()
        canvas.save()
        overlay = PdfReader(BytesIO(buffer.getvalue())).pages[0]
        page.merge_translated_page(overlay, float(crop.left), float(crop.bottom))
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
