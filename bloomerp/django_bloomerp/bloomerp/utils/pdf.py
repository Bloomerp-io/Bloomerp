from xhtml2pdf import pisa
import requests
import os
from io import BytesIO
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from PIL import Image

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

def link_callback(uri, rel):
    """Link callback function to handle external images."""
    if uri.startswith("http://") or uri.startswith("https://"):
        # If the URI is an external image, fetch and return its local path
        return fetch_image(uri)
    else:
        # If it's a local file path, resolve it and return
        return uri


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
    PDF generation function using xhtml2pdf
    
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
    # Get page size
    if not page_size:
        page_size = "A4"
    
    elif page_size not in ["A4", "letter", "A3"]:
        page_size = "A4"


    footer_content = ""
    # Page number
    if include_page_numbers:
        footer_content = "Page <pdf:pagenumber> of <pdf:pagecount>"
    else:
        footer_content = ""

    if footer:
        footer_content = footer_content + ' - ' + footer
    

    # Adjust the page margin and orientation via inline CSS
    orientation = "landscape" if is_landscape else "portrait"

    # Get header image from URL
    if header_url:
        header_path = link_callback(header_url, '')

        # Get the image dimensions
        header_image = Image.open(header_path)
        w, h = header_image.size

        # Calculate the aspect ratio for the header image
        aspect_ratio = w / h

        # Calculate width based on aspect ratio
        header_width = header_height * aspect_ratio

        # Create the header content
        header_content = f'<img src="{header_path}" width="{header_width}in" height="{header_height}in"/>'
    else:
        header_content = ""

    # Define the CSS for the PDF
    if not css_content:
        css_content = ""

    # Page orientation and margin
    orientation = "landscape" if is_landscape else "portrait"

    
    # Calculate page margin-top based on header height
    page_margin_top = header_margin_top + header_height + header_margin_bottom

    if page_margin_top < page_margin:
        page_margin_top = page_margin

    DOCUMENT = f'''
    <document pagesize='letter'>
    <head>
        <title>{ title }</title>
        <style type="text/css">
            @page {{
                size: {page_size} {orientation};
                margin: {page_margin}in;
                margin-top: {page_margin_top}in;

                @frame header {{
                    -pdf-frame-content: headerContent;
                    top: {header_margin_top}in;
                    margin-left: {header_margin_left}in;
                    margin-right: {header_margin_right}in;
                }}
                @frame footer {{
                    -pdf-frame-content: footerContent;
                    bottom: 0in;
                    margin-left: {page_margin}in;
                    margin-right: {page_margin}in;
                    height: 1cm;
                    right: 0in;
                }}
            }}

            {css_content}
        </style>
    </head>
    <body>
    <div id='headerContent'>
        {header_content}
    </div>
    <div>
        <keepinframe>
        {html_content}
        </keepinframe>
    </div>
    <div id='footerContent'>
        {footer_content}
    </div>
    </body>
    </document>
    '''    


    # Create an in-memory buffer
    pdf_buffer = BytesIO()

    # Create the PDF using xhtml2pdf's pisa
    pisa_status = pisa.CreatePDF(
        src=DOCUMENT,
        dest=pdf_buffer,
        link_callback=link_callback  # For handling images from URLs
    )

    # Check if the PDF was generated successfully
    if pisa_status.err:
        return None
    else:
        pdf_buffer.seek(0)  # Move the buffer cursor to the beginning
        return pdf_buffer.getvalue()
    



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
