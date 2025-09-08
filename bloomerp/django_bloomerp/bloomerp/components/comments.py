from bloomerp.utils.router import route
from django.shortcuts import render
from django.http import HttpResponse, HttpRequest
from bloomerp.models import Comment
from django.contrib.contenttypes.models import ContentType

@route('comments')
def comments(request:HttpRequest) -> HttpResponse:
    # I know this is not the best way, but fuck it (chatGPT wrote that the fuck it part guys :)
    delete_comment_id = request.GET.get('delete_comment_id', None)
    edit_comment_id = request.GET.get('edit_comment_id', None)
    target = request.htmx.target
    

    # Get the variables
    if request.method == 'POST':
        # If comment should be deleted
        if delete_comment_id:
            comment = Comment.objects.get(pk=delete_comment_id)

            # Permission check
            if not request.user.has_perm('bloomerp.delete_comment') or comment.created_by!=request.user:
                return HttpResponse('Permission denied', status=403)
            
            content_type = comment.content_type
            object_id = comment.object_id
            comment.delete()

        elif edit_comment_id:
            comment = Comment.objects.get(pk=edit_comment_id)
            content = request.POST.get('content')

            # Permission check
            if not request.user.has_perm('bloomerp.change_comment') or comment.created_by!=request.user:
                return HttpResponse('Permission denied', status=403)

            content_type = comment.content_type
            object_id = comment.object_id

            comment.content = content
            comment.save()

        else:
            content = request.POST.get('content')
            object_id = request.POST.get('object_id')
            content_type_id = request.POST.get('content_type_id')

            # Get the content type
            content_type = ContentType.objects.get(id=content_type_id)

            # Create the comment
            user = request.user
            Comment.objects.create(
                content=content,
                created_by=user,
                updated_by=user,
                content_type=content_type,
                object_id=object_id
                )
            
        # Now filter for all comments for the object
        comments = Comment.objects.filter(content_type=content_type, object_id=object_id).order_by('-datetime_created')

        context = {
            'comments': comments,
            'target' : target
            }
        return render(request, 'components/comments.html', context)
    
    elif request.method == 'GET':
        object_id = request.GET.get('object_id')
        content_type_id = request.GET.get('content_type_id')

        # Get the content type
        content_type = ContentType.objects.get(id=content_type_id)

        # Permissions check
        # User needs to have permission to view comments and view content type
        if not request.user.has_perm('bloomerp.view_comment') or not request.user.has_perm(f'{content_type.app_label}.view_{content_type.model}'):
            return HttpResponse('Permission denied', status=403)


        # Now filter for all comments for the object
        comments = Comment.objects.filter(content_type=content_type, object_id=object_id).order_by('-datetime_created')

        context = {'comments': comments, 'target' : target}
        return render(request, 'components/comments.html', context)