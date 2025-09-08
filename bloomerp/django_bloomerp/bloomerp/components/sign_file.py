from bloomerp.utils.router import route
from django.shortcuts import render, redirect
from django.http import HttpResponse, HttpRequest
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from bloomerp.models import File
from bloomerp.utils.document_templates import DocumentController
import base64
from django.utils.safestring import mark_safe


@login_required
@require_POST
@route('sign_file')
def sign_file(request:HttpRequest) -> HttpResponse:
    '''
    Post data to sign a file.
    
    POST Args:
        file_id (int): The id of the file to sign.
        signature (bytes): The bytes of the signature.
    '''
    # Some permissions check
    if not request.user.has_perm('bloomerp.view_file'):
        return HttpResponse('User does not have permission to view files')
    
    signature_data = request.POST.get('signature')

    try:
        file_id = request.POST.get('file_id')
    except:
        return HttpResponse('Invalid file id', status=200)

    try:
        # Get the bytes of the signature
        signature_data = base64.b64decode(signature_data.split(",")[1])

        # Get the file or return a 404
        file = File.objects.get(id=file_id)

        # Sign the file
        document_controller = DocumentController(user=request.user)

        # Sign the file
        signed_file = document_controller.sign_pdf(file, signature_data)    

        # Display success message
        messages.success(request, f'File has been signed')

        # Redirect user to page where request was made
        return redirect(request.META.get('HTTP_REFERER', '/'))
    
    except Exception as e:
        messages.error(request, f'Error signing file: {e}')
        return redirect(request.META.get('HTTP_REFERER', '/'))