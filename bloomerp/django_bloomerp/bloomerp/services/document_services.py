from bloomerp.models import DocumentTemplate
from bloomerp.models import AbstractBloomerpUser
from django.db.models import Model
from bloomerp.models import File

class DocumentTemplateService:

    def __init__(self, user:AbstractBloomerpUser):
        self.user = user    

    def create_document_from_template(
        self,
        document_template:DocumentTemplate,
        instance:Model,
        persist:bool=True,
    ):
        """Creates a document based on a document template and a model instance."""
        pass

