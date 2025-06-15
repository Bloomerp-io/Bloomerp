from bloomerp.utils.router import route
from django.shortcuts import render
from django.http import HttpResponse, HttpRequest
from bloomerp.forms.core import BloomerpModelForm
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.decorators import login_required
from django.forms.models import modelform_factory
from django.contrib import messages
from bloomerp.models import File
from django.shortcuts import get_object_or_404

@login_required
@route('bulk_update_objects')
def bulk_update_objects(request:HttpRequest) -> HttpResponse:
    # Get the content type id and form prefix from the query parameters
    content_type_id = request.GET.get('content_type_id')
    form_prefix = request.GET.get('bulk_update_form_prefix','')
    user = request.user
    num_objects = 0


    # Initialize potential errors
    errors = []

    if request.method == 'POST':
        # Get objects to update
        object_ids = request.POST.getlist('object_ids')
        ct = get_object_or_404(ContentType, pk=content_type_id)
        model = ct.model_class()
        objects = model.objects.filter(id__in=object_ids)
        delete_objects = request.POST.get('delete_objects', False)            
        

        # Number of objects
        num_objects = len(objects)
        num_errors = 0

        # If delete_objects has a value
        if delete_objects in ['true', 'True']:
            if not user.has_perm(f'{model._meta.app_label}.bulk_delete_{model._meta.model_name}'):
                return HttpResponse('Permission denied', status=403)

            # Check whether the model is a file
            if model == File:
                for obj in objects:
                    obj.delete()
            else:
                objects.delete()
            messages.success(request, f"Successfully deleted {num_objects} objects")
        else:
            # If the user does not have permission to update the model
            if not user.has_perm(f'{model._meta.app_label}.bulk_change_{model._meta.model_name}'):
                return HttpResponse('Permission denied', status=403)

            # Get all of the fields that are being updated from request.POST using the form_prefi
            fields = []
            if not form_prefix:
                return HttpResponse('form_prefix required in the query parameters', status=400)
            x = len(form_prefix) + 1 # The length of the form_prefix plus the underscore Ex. 'form_prefix_'
            for key in request.POST:
                if key.startswith(form_prefix):
                    fields.append(key[x:])
            
            # Create a formset with the fields
            Form = modelform_factory(model, fields=fields, form=BloomerpModelForm)

            # Loop through the objects and update them
            
            for obj in objects:
                form = Form(data=request.POST, files=request.FILES, prefix=form_prefix, instance=obj, model=model, user=user)
                if form.is_valid():
                    form.save()
                else:
                    errors.append(
                        {
                            "object" : obj,
                            "errors" : form.errors
                        }
                    )
            # Get number of errors
            num_errors = len(errors)
            if num_errors == num_objects:
                messages.error(request, f"Failed to update {num_errors} objects")
            elif num_errors > 0:
                messages.warning(request, f"Bulk update paritally completed. Failed to update {num_errors} objects")
            else:
                messages.success(request, f"Successfully updated {num_objects} objects")

    context = {
        "errors": errors,
        "num_objects": num_objects,
        "num_errors": num_errors
    }
    return render(request, 'components/bulk_update_objects.html', context)