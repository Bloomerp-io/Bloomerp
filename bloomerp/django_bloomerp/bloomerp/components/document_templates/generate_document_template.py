from bloomerp.utils.router import route
from django.shortcuts import render
from django.http import HttpResponse, HttpRequest
from bloomerp.utils.document_templates import DocumentController
from bloomerp.models import DocumentTemplate, File
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from bloomerp.forms.document_templates import GenerateDocumentForm
import base64
from bloomerp.utils.requests import parse_bool_parameter

@login_required
@route('generate_document_template')
def generate_document_template(request:HttpRequest) -> HttpResponse:
    '''
    Component that generates a document template.

    GET Arguments:
        - document_template_id : The document template ID
        - add_persist_field : Whether to add the option to persist the document
    
    POST Arguments:
        - form : The form data
        - preview_content : Content to preview for the document template (optional)
        - add_persist_field : add_persist_field (optional)
        

    '''
    # Some permissions check
    if not request.user.has_perm('bloomerp.view_documenttemplate'):
        return HttpResponse('User does not have permission to view document templates')

    if request.method == 'POST':
        # Get document template from the form
        document_template_id = request.POST.get('document_template_id')
        document_template = get_object_or_404(DocumentTemplate, id=document_template_id)

        # Check whether there is preview content
        preview_content = request.POST.get('preview_content', None)
        
        # Get add persist field for later form creation
        add_persist_field = parse_bool_parameter(request.POST.get('add_persist_field'), True)

        if preview_content:
            document_template.template = preview_content

        # Get the form data
        form = GenerateDocumentForm(
            document_template=document_template, 
            data = request.POST, 
            files = request.FILES,
            add_persist_field=add_persist_field
            )
        
        # If form is not valid return from
        if not form.is_valid():
            return render(request, 'components/generate_document_template.html', context={'form': form})
        else:
            try:
                # Get the cleaned data from the form
                data = form.cleaned_data

                # Initialize the document controller
                document_controller = DocumentController(document_template, request.user)

                # Generate the document without persisting
                file: File = document_controller.create_document(
                    document_template=document_template,
                    free_variables = data, 
                    instance=form.instance,
                    persist=form.persist
                )

                # Ensure the file is associated
                if not file.file:
                    return HttpResponse('File not associated correctly', status=500)

                # Get the bytes of the file
                file_bytes = file.file.read()
                file_base64 = base64.b64encode(file_bytes).decode('utf-8')

                return render(request, 'components/generate_document_template.html', context={'file_bytes': file_base64, 'form':form})
            except TypeError as e:
                if 'RelatedManager' in str(e):
                    form.add_error(None, "Please make sure that when using a for-loop, '.all' is used at the end.")
                else:
                    form.add_error(None, str(e))
                return render(request, 'components/generate_document_template.html', context={'form': form})
            except Exception as e:
                form.add_error(None, str(e))
                return render(request, 'components/generate_document_template.html', context={'form': form})
            
    else:
        # Get the document template from the GET request
        document_template_id = request.GET.get('document_template_id')
        
        # Get the persist option
        add_persist_field = parse_bool_parameter(request.GET.get('add_persist_field'), False)

        # Get the document template
        document_template = get_object_or_404(DocumentTemplate, id=document_template_id)

        # Create the form
        form = GenerateDocumentForm(document_template=document_template, add_persist_field=add_persist_field)

        return render(request, 'components/generate_document_template.html', context={'form': form})
