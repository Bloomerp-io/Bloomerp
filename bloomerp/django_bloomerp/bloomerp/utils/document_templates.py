from bloomerp.models.document_templates import DocumentTemplate
from bloomerp.models.files import File
from bloomerp.models.files.file import DocumentTemplateFileMetadata, FileMetadata, FileSignatureMetadata
from typing import Any
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.utils.pdf import generate_pdf
from django.db.models import Model
from django.core.files.base import ContentFile
from django.template import engines
from bloomerp.utils.pdf import PdfHandler

from django.contrib.auth import get_user_model
User = get_user_model()

class DocumentController:
    '''
    Controller class for everything related to documents.
    '''

    def __init__(self, document_template : DocumentTemplate=None, user : AbstractBloomerpUser = None) -> None:
        self.document_template = document_template
        self.user = user

    def create_document(
            self,
            document_template:DocumentTemplate, 
            instance: Model | None,
            free_variables: dict[str, Any] | None = None,
            persist: bool = True,
        ) -> File | ContentFile:
        ''' Creates a document for a particular template, using the model variable and the free variables:
            - Template : The document template
            - Instance : The model instance
            - Free variables : A dictionary of free variables

        '''
        data = {}

        if instance:
            data['object'] = instance
    	
        data["vars"] = free_variables or {}

        #Create metadata variable
        meta_data = FileMetadata(
            document_template=DocumentTemplateFileMetadata(
                id=document_template.pk, name=document_template.name,
            ),
            signature=FileSignatureMetadata(signed=False),
        )
        
        #Format HTML       
        django_engine = engines["django"]
        temp = django_engine.from_string("{% load document_template_tags %}" + document_template.template)
        formatted_html = temp.render(data)        

        styling = document_template.get_combined_styling()

        # Check if document_template has a header
        if document_template.template_header:
            header = document_template.template_header
            header_url = header.header.path
            header_margin_bottom = header.margin_bottom
            header_margin_left = header.margin_left
            header_margin_right = header.margin_right
            header_margin_top = header.margin_top
            header_height = header.height
        else:
            header_url = None
            header_margin_bottom = 0
            header_margin_left = 0
            header_margin_right = 0
            header_margin_top = 0
            header_height = 0

        if document_template.page_orientation == 'landscape':
            is_landscape = True
        else:
            is_landscape = False

        document_bytes = generate_pdf(
            html_content=formatted_html,
            css_content=styling,
            # Header options
            header_url=header_url,
            header_margin_bottom=header_margin_bottom,
            header_margin_left=header_margin_left,
            header_margin_right=header_margin_right,
            header_margin_top=header_margin_top,
            header_height=header_height,
            # Page options
            title=document_template.name,
            page_size=document_template.page_size,
            page_margin=document_template.page_margin,
            footer=document_template.footer,
            is_landscape=is_landscape,
            include_page_numbers=document_template.include_page_numbers
        )

        content_file = ContentFile(document_bytes)
        
        if persist:
            file_object = File(
                name=f"{document_template.name} {instance}",
                content_object=instance, persisted=True, meta=meta_data,
                created_by=self.user, updated_by=self.user,
                folder=document_template.save_to_folder,
            )
            file_object.file.save(f"{file_object.name}.pdf", content_file)
            return file_object
        return content_file

    def create_preview_document(
            self,
            document_template:DocumentTemplate,
            data:dict
        ) -> ContentFile:
        ''' Creates a preview document for a particular document_template, using the model variable and the free variables:
            - Template : The document document_template
            - Data : A dictionary of free variables
        '''
        #Format HTML
        django_engine = engines["django"]
        data.setdefault("vars", {})
        temp = django_engine.from_string("{% load document_template_tags %}" + document_template.template)
        formatted_html = temp.render(data)
        

        styling = document_template.get_combined_styling()

        # Check if document_template has a header
        if document_template.template_header:
            header = document_template.template_header
            header_url = header.header.path
            header_margin_bottom = header.margin_bottom
            header_margin_left = header.margin_left
            header_margin_right = header.margin_right
            header_margin_top = header.margin_top
            header_height = header.height
        else:
            header_url = None
            header_margin_bottom = 0
            header_margin_left = 0
            header_margin_right = 0
            header_margin_top = 0
            header_height = 0

        if document_template.page_orientation == 'landscape':
            is_landscape = True
        else:
            is_landscape = False

        document_bytes = generate_pdf(
            html_content=formatted_html,
            css_content=styling,
            # Header options
            header_url=header_url,
            header_margin_bottom=header_margin_bottom,
            header_margin_left=header_margin_left,
            header_margin_right=header_margin_right,
            header_margin_top=header_margin_top,
            header_height=header_height,
            # Page options
            title=document_template.name,
            page_size=document_template.page_size,
            page_margin=document_template.page_margin,
            footer=document_template.footer,
            is_landscape=is_landscape,
            include_page_numbers=document_template.include_page_numbers,
        )

        content_file = ContentFile(document_bytes)

        return content_file

    def sign_pdf(
            self, 
            file : File, 
            signature_bytes : bytes
            ) -> File:
        '''
        Function that will sign a pdf file, using signature bytes.
        '''
        file_path = file.file.path

        # Preserve template provenance and type the signature information.
        meta_data = FileMetadata(
            document_template=file.metadata.document_template,
            signature=FileSignatureMetadata(
                signed=True, user_id=self.user.pk if self.user else None,
            ),
        )

        # Create a PdfHandler object
        handler = PdfHandler(file_path)

        #Sign the actual document and retreive the bytes
        document_bytes = handler.sign_pdf(
            signature_path=None,
            signature_bytes= signature_bytes
        )

        # Create a content file
        content_file = ContentFile(document_bytes)
        
        # Save the signed output with validated provenance and its generic owner.
        signed_file_obj = File(
            name=f"{file.name} - signed.pdf", content_object=file.linked_object,
            persisted=True, meta=meta_data, created_by=self.user, updated_by=self.user,
        )
        signed_file_obj.file.save(signed_file_obj.name, content_file)

        # Update the original file with the signed file id
        file.meta = file.metadata.model_copy(update={
            "signature": FileSignatureMetadata(signed_file_id=signed_file_obj.pk),
        })
        file.save()

        return signed_file_obj
        

