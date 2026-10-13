from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.router import router
from django.shortcuts import render
from django.http import HttpResponse, HttpRequest
from bloomerp.models import Comment, ApplicationField
from django.core.exceptions import ValidationError
from django.db import transaction
from django.views.decorators.http import require_http_methods
from bloomerp.services.object_reference_services import parse_editor_references, validate_reference, reconcile_references

from bloomerp.permissions.manager import UserPolicyManager, create_permission_str


from bloomerp.utils.models import get_object_model_and_content_type_or_404


@router.register(
    path='components/comments/<int:content_type_id>/<int_or_uuid:object_id>', 
    url_name='components_comments'
)
@require_http_methods(["GET", "POST"])
def comments(request:HttpRequest, content_type_id:int, object_id:str) -> HttpResponse:
    """Render comments for an object after checking its view permission."""
    object, _, content_type = get_object_model_and_content_type_or_404(content_type_id, object_id)
    
    # Check permissions
    permission_manager = UserPolicyManager(request.user)
    if not permission_manager.has_access_to_object(
        object,
        BloomerpPermission.VIEW,
    ):
        return HttpResponse("You don't have access to the comments of this object", status=403)
    
    if request.method == "POST":
        comment_text = request.POST.get("comment", "")
        if not request.user.is_authenticated or not comment_text.strip():
            return HttpResponse("A comment is required", status=400)
        application_field = ApplicationField.get_by_field(Comment, "content")
        try:
            content, references = parse_editor_references(comment_text, application_field)
            for reference in references:
                validate_reference(request, reference, object)
            with transaction.atomic():
                comment = Comment.objects.create(content=content, content_type=content_type, object_id=str(object.pk), created_by=request.user)
                reconcile_references(comment, {application_field.pk: references}, None, request)
        except ValidationError as error:
            return HttpResponse("; ".join(error.messages), status=400)

    # Retrieve the comments
    comments = Comment.objects.filter(
        content_type=content_type,
        object_id=object.id
    )
    highlighted_comment_id = request.GET.get("highlight", "")
    if not highlighted_comment_id.isdecimal():
        highlighted_comment_id = ""
    
    return render(
        request,
        "components/objects/details/comments.html",
        context={
            "object" : object,
            "content_type_id" : content_type_id,
            "comments" : comments,
            "highlighted_comment_id": highlighted_comment_id,
        }
    )
