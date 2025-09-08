import io
from bloomerp.utils.router import route
from django.shortcuts import render
from django.http import FileResponse, HttpRequest, HttpResponse
from django.contrib.contenttypes.models import ContentType
from bloomerp.utils.model_io import BloomerpModelIO
from bloomerp.forms.core import BloomerpDownloadBulkUploadTemplateForm
from django.contrib.auth.decorators import login_required

@login_required
@route('download_bulk_upload_template')
def download_bulk_upload_template(request: HttpRequest) -> FileResponse:
    '''Save the bulk upload template for a model as a CSV or Excel file.'''
    form = BloomerpDownloadBulkUploadTemplateForm(data=request.POST)

    if not form.is_valid():
        # Print form errors explicitly
        print("Form errors:", form.errors)
        return HttpResponse('Invalid form data', status=400)

    # Get the selected fields from the form
    fields = form.get_selected_fields()
    
    file_type = form.cleaned_data.get('file_type')
    model = form.model

    # Permission check
    if not request.user.has_perm(f'{model._meta.app_label}.add_{model._meta.model_name}'):
        return HttpResponse('User does not have permission to download the bulk upload template', status=403)

    if not model:
        return HttpResponse('Model not found', status=400)

    model_io = BloomerpModelIO(model)

    if file_type == 'csv':
        template_bytes = model_io.create_model_template(file_type='csv', fields=fields)
        content_type = 'text/csv'
        extension = 'csv'
    elif file_type == 'xlsx':
        template_bytes = model_io.create_model_template(file_type='xlsx', fields=fields)
        content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        extension = 'xlsx'
    else:
        return HttpResponse('Invalid export format', status=400)

    # Wrap the bytes in a BytesIO object
    byte_stream = io.BytesIO(template_bytes)

    # Explicitly set the Content-Disposition header
    response = HttpResponse(byte_stream, content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename={model.__name__}__bulk_upload_template.{extension}'

    return response