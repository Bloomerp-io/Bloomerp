import base64

from bloomerp.router import router
from django.shortcuts import render
from django.http import HttpResponse, HttpRequest
from bloomerp.models.document_templates import DocumentTemplate
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from bloomerp.services.document_services import DocumentTemplateService
from django.contrib.contenttypes.models import ContentType

from bloomerp.services.permission_services import UserPermissionManager, create_permission_str

@router.register(
    path='components/document_templates/generate/<str:id>/', 
    name='components_generate_document_template'
    )
@login_required
def generate_document_template(
    request:HttpRequest, 
    id:str,
    ) -> HttpResponse:
    """Component to generate document templates

    Args:
        request (HttpRequest): the request object
        id (str): the ID of the document template
        
    GET Args:
        content_type_id (str, optional): the content type ID of the object to generate the document template for. Defaults to None.
        object_id (str, optional): the object ID of the object to generate the document template for. Defaults to None.

    Returns:
        HttpResponse: response containing a form
    """
    # Get the document template
    document_template = get_object_or_404(
        DocumentTemplate,
        id=id
    )
    service = DocumentTemplateService(document_template, request.user)
    
    # Perform permission check
    # TODO: We need a more elaborate permission system that checks the fields here
    permission_manager = UserPermissionManager(request.user)
    for content_type in list(document_template.content_types.all()) + [ContentType.objects.get_for_model(DocumentTemplate)]:
        if not permission_manager.has_global_permission(
            content_type,
            create_permission_str(
                content_type.model_class(),
                "view"
            )
        ):
            return HttpResponse("You do not have permission to view this document template.", status=403)
    
    # Conditionally get the object ID and template ID
    content_type_id = request.GET.get("content_type_id")
    object_id = request.GET.get("object_id")
    instance = None
    if content_type_id and object_id:
        content_type : ContentType = get_object_or_404(
            ContentType,
            id=content_type_id
        )
        instance = get_object_or_404(
            content_type.model_class(),
            id=object_id
        )
    
    # Get the form instance
    form = service.get_form(
        instance=instance
    )(
        data=request.POST if request.method == "POST" else None,
    )
    
    context = {
        "form" : form,
        "id" : id,
        "form_action": request.get_full_path(),
        "files" : service.get_files(instance).order_by("-datetime_created")
    }
    
    match request.method:
        case "GET":
            return render(
                request,
                "components/document_templates/generate_document_template.html",
                context
            )    
        
        case "POST":
            if form.is_valid():
                pdf_bytes = service.generate(form)
                generated_file = None
                if form.cleaned_data.get("persist"):
                    generated_file = service.create_file(
                        pdf_bytes,
                        instance=getattr(form, "instance", None),
                    )
                
                # Add extra context
                context["file_bytes"] = base64.b64encode(pdf_bytes).decode("ascii")
                context["generated_file"] = generated_file
                
                # Reload the files in case a new one was generated
                context["files"] = service.get_files(getattr(form, "instance", instance)).order_by("-datetime_created")
                
                return render(
                    request,
                    "components/document_templates/generate_document_template.html",
                    context
                )
            else:
                return render(
                    request,
                    "components/document_templates/generate_document_template.html",
                    context
                )
