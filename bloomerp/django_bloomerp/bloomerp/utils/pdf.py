import html
import json
import requests
import os
from io import BytesIO
from pathlib import Path
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from PIL import Image
from typing import Optional
from enum import Enum
from django.conf import settings


def _configure_weasyprint_native_library_path() -> None:
    homebrew_lib = "/opt/homebrew/lib"
    if os.path.isdir(homebrew_lib):
        existing = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
        paths = [path for path in existing.split(":") if path]
        if homebrew_lib not in paths:
            os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join([homebrew_lib, *paths])


_configure_weasyprint_native_library_path()

from weasyprint import HTML, default_url_fetcher

def fetch_image(image_url):
    """Helper function to download image from a URL and save it temporarily."""
    try:
        response = requests.get(image_url)
        if response.status_code == 200:
            # Save the image temporarily in memory
            temp_image_path = os.path.join(os.getcwd(), "temp_image.jpg")
            with open(temp_image_path, 'wb') as img_file:
                img_file.write(response.content)
            return temp_image_path
        return None
    except Exception as e:
        print(f"Error fetching image: {e}")
        return None


def _resolve_local_path(uri: str, rel: str | None = None) -> str:
    """Resolve local URLs/paths to filesystem paths when possible."""
    if not uri:
        return uri

    if os.path.isabs(uri) and os.path.exists(uri):
        return uri

    media_root = getattr(settings, "MEDIA_ROOT", "") if settings.configured else ""
    media_url = (getattr(settings, "MEDIA_URL", "") if settings.configured else "").strip("/")

    if media_root and media_url:
        prefixes = [
            f"/{media_url}/",
            f"{media_url}/",
        ]
        for prefix in prefixes:
            if uri.startswith(prefix):
                relative_media_path = uri[len(prefix):]
                resolved = os.path.join(media_root, relative_media_path)
                if os.path.exists(resolved):
                    return resolved

    if rel and not os.path.isabs(uri):
        candidate = os.path.join(os.path.dirname(rel), uri)
        if os.path.exists(candidate):
            return candidate

    return uri

def link_callback(uri, rel):
    """Link callback function to handle external images."""
    if uri.startswith("http://") or uri.startswith("https://"):
        # If the URI is an external image, fetch and return its local path
        return fetch_image(uri)
    else:
        # If it's a local file/media path, resolve it to a filesystem path when possible.
        return _resolve_local_path(uri, rel)


def _as_weasyprint_url(uri: str, rel: str | None = None) -> str:
    resolved = _resolve_local_path(uri, rel)
    if resolved and os.path.isabs(resolved) and os.path.exists(resolved):
        return Path(resolved).as_uri()
    return resolved


def _resolve_image_path_for_dimensions(uri: str) -> str:
    if uri.startswith("http://") or uri.startswith("https://"):
        return fetch_image(uri)
    return _resolve_local_path(uri, "")


def weasyprint_url_fetcher(url: str):
    """Resolve local media/file URLs before delegating to WeasyPrint."""
    return default_url_fetcher(_as_weasyprint_url(url))


def get_weasyprint_base_url() -> str:
    if settings.configured:
        return str(getattr(settings, "BASE_DIR", os.getcwd()))
    return os.getcwd()


def generate_pdf(
        html_content:str, 
        css_content:str|None=None,
        font_url=None, 
        page_margin=1,
        is_landscape=False,
        # Header options
        header_url:str=None,
        header_height:float=1.0,
        header_margin_top:float=0.5,
        header_margin_bottom:float=0.0,
        header_margin_left:float=1.0,
        header_margin_right:float=1.0,
        # Page size options
        page_size:str = None,
        include_page_numbers:bool = True,
        # Footer options
        footer : str = None,
        title:str = "PDF Document"
        )->bytes:
    '''
    PDF generation function using WeasyPrint
    
    Args:
        html_content (str): The HTML content to be converted to PDF.
        css_content (str): The CSS content for styling the PDF.
        font_url (str): The URL to the font file.
        page_margin (int): The margin of the page in inches.
        is_landscape (bool): Whether the page should be in landscape mode.
        header_url (str): The URL to the header image.
        header_margin_top (int): The top margin of the header in inches.
        header_margin_bottom (int): The bottom margin of the header in inches.
        header_margin_left (int): The left margin of the header in inches.
        header_margin_right (int): The right margin of the header in inches.
        page_size (str): The size of the page (A4, letter, A3).
        include_page_numbers (bool): Whether to include page numbers in the footer.
        footer (str): The footer content.
        title (str): The title of the PDF document.

    Returns:
        bytes: The generated PDF as bytes.
    '''
    normalized_page_size = (page_size or "A4").strip()
    page_size_aliases = {
        "a4": "A4",
        "a3": "A3",
        "letter": "letter",
    }
    page_size = page_size_aliases.get(normalized_page_size.lower(), "A4")

    footer_text = footer or ""
    orientation = "landscape" if is_landscape else "portrait"

    # Get header image from URL
    if header_url:
        header_path = _as_weasyprint_url(header_url, '')

        # Get the image dimensions
        header_image_path = _resolve_image_path_for_dimensions(header_url)
        header_image = Image.open(header_image_path)
        w, h = header_image.size

        # Calculate the aspect ratio for the header image
        aspect_ratio = w / h

        # Calculate width based on aspect ratio
        header_width = header_height * aspect_ratio

        # Create the header content
        header_content = f'<img src="{header_path}" width="{header_width}in" height="{header_height}in"/>'
    else:
        header_content = ""
        header_height = 0
        header_margin_top = 0
        header_margin_bottom = 0

    # Define the CSS for the PDF
    if not css_content:
        css_content = ""

    # Calculate page margin-top based on header height
    page_margin_top = max(page_margin, header_margin_top + header_height + header_margin_bottom)

    page_margin_css = f"{page_margin_top}in {page_margin}in {page_margin}in {page_margin}in"
    header_page_css = ""
    if header_content:
        header_page_css = """
            @top-left {
                content: element(headerContent);
            }
        """

    footer_content_css = ""
    if include_page_numbers and footer_text:
        footer_content_css = f'"Page " counter(page) " of " counter(pages) {json.dumps(" - " + footer_text)}'
    elif include_page_numbers:
        footer_content_css = '"Page " counter(page) " of " counter(pages)'
    elif footer_text:
        footer_content_css = json.dumps(footer_text)

    footer_page_css = ""
    if footer_content_css:
        footer_page_css = f"""
            @bottom-center {{
                content: {footer_content_css};
                font-size: 9pt;
            }}
        """

    font_face_css = ""
    if font_url:
        font_face_css = f"""
            @font-face {{
                font-family: "DocumentFont";
                src: url("{_as_weasyprint_url(font_url)}");
            }}
            body {{
                font-family: "DocumentFont";
            }}
        """

    page_css = f"""
        @page {{
            size: {page_size} {orientation};
            margin: {page_margin_css};
            {header_page_css}
            {footer_page_css}
        }}

        #headerContent {{
            position: running(headerContent);
        }}

        {font_face_css}
    """

    document = f'''
    <!doctype html>
    <html>
        <head>
            <meta charset="utf-8">
            <title>{ html.escape(title) }</title>
            <style type="text/css">
                {page_css}
                {css_content}
            </style>
        </head>
        <body>
            <div id='headerContent'>
                {header_content}
            </div>
            <div>
                {html_content}
            </div>
        </body>
    </html>
    '''    

    return HTML(
        string=document,
        base_url=get_weasyprint_base_url(),
        url_fetcher=weasyprint_url_fetcher,
    ).write_pdf()
    

class PdfHandler:
    def __init__(self, file: str):
        self.file = file

    def sign_pdf(self,  
                signature_path: str = None,
                signature_bytes: bytes = None,
                width: int = 140,
                height: int = 70,
                x: int = 380,
                y: int = 5,
                border: bool = False):
        # Open the existing PDF and create a new PDF writer
        existing_pdf = PdfReader(self.file)
        output_pdf = PdfWriter()

        # Create a canvas to draw on the new PDF page
        packet = BytesIO()
        can = canvas.Canvas(packet, pagesize=letter)

        # Load and draw the signature image
        if signature_bytes:
            io = BytesIO(signature_bytes)
            image = Image.open(io)
            transp = Image.new('RGBA', image.size, (255, 255, 255, 0))
            transp.paste(image, (0, 0), image)

            # Create a new file-like object to receive PNG data.
            buf = BytesIO()
            transp.save(buf, format='PNG')
            buf.seek(0)
            signature_image = ImageReader(buf)
        elif signature_path:
            signature_image = ImageReader(signature_path)
        else:
            raise ValueError("Either signature_path or signature_bytes must be provided.")

        for page in existing_pdf.pages:
            can.showPage()
            can.drawImage(signature_image, x, y, width, height)

            if border:
                can.rect(x, y, width, height, stroke=1, fill=0)

        # Save the canvas to the packet and close it
        can.save()
        packet.seek(0)

        # Add the modified page to the new PDF
        new_pdf_pages = PdfReader(packet).pages
        for i, page in enumerate(existing_pdf.pages):
            page.merge_page(new_pdf_pages[i+1])
            output_pdf.add_page(page)

        # Save the modified PDF to a bytes object
        modified_pdf_bytes = BytesIO()
        output_pdf.write(modified_pdf_bytes)
        modified_pdf_bytes.seek(0)

        # Return bytes
        return modified_pdf_bytes.getvalue()


class PageSize(Enum):
    A4 = "A4"
    LETTER = "letter"
    A3 = "A3"


class PageOrientation(Enum):
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"


class PDFDocumentGenerator:
    content:str

    def __init__(
            self, 
            content:str,
            footer:str = None,
            title:str = "PDF Document",
            page_size:PageSize = PageSize.A4,
            page_orientation:PageOrientation = PageOrientation.PORTRAIT,
            ):
        self.content = content
        self.footer = footer
        self.title = title
        self.page_size = page_size
        self.page_orientation = page_orientation

    def generate_pdf(self) -> bytes:
        """Generates a PDF document based on the provided content and settings.
    
        Returns:
            bytes: The generated PDF document as a byte stream.
        """
        pass

    def add_signature(self, signature_bytes: bytes, slot_name:Optional[str] = None):
        """
        Adds a signature to the PDF document at the specified slot.
        If the slot is not found, or if no slot_name is provided, the 
        signature will be added to the available slot.

        If no slot is available, no signature will be added.

        Args:
            signature_bytes (bytes): The bytes of the signature image.
            slot_name (str, optional): The name of the slot where the signature should be placed. Defaults to None.

        Returns:
            None: The actual generation happens within the generate_pdf function, this function just modifies the content to include the signature.
        """
        pass

    
