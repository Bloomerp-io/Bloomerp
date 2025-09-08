from bloomerp.models import DocumentTemplate, FileFolder, File, AbstractBloomerpUser
from bloomerp.utils.pdf import generate_pdf
from django.db.models import Model
from django.core.files.base import ContentFile
from django.template import engines
from django.template.loader import render_to_string
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
            instance:Model, 
            free_variables: dict=None,
            persist:bool=True
        ):
        ''' Creates a document for a particular template, using the model variable and the free variables:
            - Template : The document template
            - Instance : The model instance
            - Free variables : A dictionary of free variables

        '''
        data = {}

        if instance:
            data['object'] = instance
    	
        #Add free variable data
        if free_variables:
            data.update(free_variables)

        #Create metadata variable
        meta_data = {}
        meta_data['document_template'] = document_template.pk

        meta_data['signed'] = False
        
        #Format HTML       
        django_engine = engines["django"]
        temp = django_engine.from_string(document_template.template)
        formatted_html = temp.render(data)        

        # Get the styling
        # Check if the template has styling
        if not document_template.styling:
            styling = None
        else:
            styling = document_template.styling.styling

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
            file_object = File()
        
            #Save the file
            file_object.file.save(document_template.name + ' ' + str(instance) + '.pdf', content_file)

            file_object.name = document_template.name + ' ' + str(instance)
            file_object.content_object = instance

            # Add created by
            file_object.created_by = self.user
            file_object.updated_by = self.user
            

            #Save metadata
            file_object.meta = meta_data

            file_object.save()

            if document_template.save_to_folder:
                document_template.save_to_folder.files.add(file_object)
                

            return file_object
        else:
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
        temp = django_engine.from_string(document_template.template)
        formatted_html = temp.render(data)
        

        # Check if the document_template has styling
        if not document_template.styling:
            styling = None
        else:
            styling = document_template.styling.styling

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

        # Create metadata variable
        meta_data = {}

        # If a user is present, add the user to the metadata
        if self.user:
            meta_data['user'] = self.user.pk

        # Check if the file object has a document template
        if 'document_template' in file.meta:
            meta_data['document_template'] = file.meta['document_template']

        # Add signed equals to true
        meta_data['signed'] = True

        # Create a PdfHandler object
        handler = PdfHandler(file_path)

        #Sign the actual document and retreive the bytes
        document_bytes = handler.sign_pdf(
            signature_path=None,
            signature_bytes= signature_bytes
        )

        # Create a content file
        content_file = ContentFile(document_bytes)
        
        # Create a file object
        signed_file_obj = File()

        #Save the file
        signed_file_obj.file.save(file.name + '- signed' '.pdf', content_file)

        signed_file_obj.content_object = file.content_object

        signed_file_obj.meta = meta_data
        signed_file_obj.name = file.name + '- signed.pdf' 
        signed_file_obj.save()
        
        # Update the original file with the signed file id
        file.meta = {'signed_file_id': str(signed_file_obj.pk)}
        file.save()

        return signed_file_obj
        




