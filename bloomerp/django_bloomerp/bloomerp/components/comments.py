from bloomerp.router import router
from django.shortcuts import render
from django.http import HttpResponse, HttpRequest
from bloomerp.models import Comment

from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.utils.models import get_object_model_and_content_type_or_404


@router.register(
    path='components/comments/<int:content_type_id>/<int_or_uuid:object_id>', 
    url_name='components_comments'
)
def comments(request:HttpRequest, content_type_id:int, object_id:str) -> HttpResponse:
    object, _, content_type = get_object_model_and_content_type_or_404(content_type_id, object_id)
    
    # Check permissions
    permission_manager = UserPermissionManager(request.user)
    if not permission_manager.has_access_to_object(
        object,
        create_permission_str(object, "view")
    ):
        return HttpResponse("You don't have access to the comments of this object", status=403)
    
    if request.method == "POST":
        comment_text = request.POST.get("comment")
        Comment.objects.create(
            content=comment_text,
            content_type=content_type,
            object_id=object.id,
            created_by=request.user
        )
        
    # Retrieve the comments
    comments = Comment.objects.filter(
        content_type=content_type,
        object_id=object.id
    )
    
    return render(
        request,
        "components/comments.html",
        context={
            "object" : object,
            "content_type_id" : content_type_id,
            "comments" : comments
        }
    )