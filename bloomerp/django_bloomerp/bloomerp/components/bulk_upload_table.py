from registries.route_registry import router
from django.shortcuts import render
from django.http import HttpResponse, HttpRequest
from django.core.files import File
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from bloomerp.utils.model_io import BloomerpModelIO
from django.forms.models import modelformset_factory
from django.forms import BaseFormSet
from django.views.decorators.http import require_POST


@require_POST
@router.route(path='components/bulk_upload_table/', name='components_bulk_upload_table')
@login_required
def bulk_upload_table(request:HttpRequest) -> HttpResponse:
    '''
    Component that allows for bulk uploading of data into a model.

    POST Parameters:
    - bulk_upload_file: The file to upload
    - bulk_upload_content_type_id: The content type id of the model to upload to

    '''
    bulk_upload_file:File = request.FILES.get('bulk_upload_file')
    content_type_id = request.POST.get('bulk_upload_content_type_id')
    

    # Get the model from the content type id
    if not content_type_id:
        return HttpResponse('content_type_id required in the query parameters', status=400)
    else:
        try:
            content_type_id = int(content_type_id)
            model = ContentType.objects.get(id=content_type_id).model_class()
        except ValueError:
            return HttpResponse('Invalid content type id', status=400)
        except ContentType.DoesNotExist:
            return HttpResponse('Invalid content type id', status=400)

    # Permissions check
    if not request.user.has_perm(f'{model._meta.app_label}.bulk_add_{model._meta.model_name}'):
        return HttpResponse('Permission denied', status=403)

    context = {}
    model_io = BloomerpModelIO(model)

    if bulk_upload_file:
        # Flow in case of a file upload
        try:
            data = model_io.import_from_template(bulk_upload_file)
        except Exception as e:
            return HttpResponse(f'Error importing file: {e}', status=200)
    
        fields = data[0].keys()
        Formset : BaseFormSet = modelformset_factory(model, fields=fields, extra=len(data)) 

        # Create a blank formset
        formset = Formset(queryset=model.objects.none(), initial=data, prefix = 'bulk_upload')   
    else:
        # Flow in case of a form submission
        # Get the fields that were given based on the form submission
        fields = request.POST.getlist('bulk_upload_fields')

        Formset  = modelformset_factory(model, fields=fields)
        formset : BaseFormSet = Formset(request.POST, request.FILES, prefix = 'bulk_upload')

        if formset.is_valid():
            instances = formset.save(commit=False)

            for form, instance in zip(formset.forms, instances):
                if hasattr(instance, 'created_by'):
                    instance.created_by = request.user
                if hasattr(instance, 'updated_by'):
                    instance.updated_by = request.user
                
                instance.save()

                # Call save_m2m on each form after saving the instance
                if hasattr(form, 'save_m2m'):
                    form.save_m2m()
            
            return HttpResponse('Data saved successfully', status=200)


    context['formset'] = formset
    context['fields'] = fields
    context['content_type_id'] = content_type_id
    return render(request, 'components/bulk_upload_table.html', context)