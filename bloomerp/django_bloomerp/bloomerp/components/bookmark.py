from bloomerp.utils.router import route
from django.shortcuts import render
from django.http import HttpResponse, HttpRequest
from bloomerp.models import Bookmark, AbstractBloomerpUser
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required

@csrf_exempt
@login_required
@route('bookmark')
def bookmark(request:HttpRequest) -> HttpResponse:
    # Get variables
    user:AbstractBloomerpUser = request.user
    size = request.GET.get('size', 30)

    # Get the content_type_id and object_id from the request
    try:
        content_type_id = int(request.GET.get('content_type_id'))
        object_id = int(request.GET.get('object_id'))
    except:
        return HttpResponse(status=400)

    if not user.is_authenticated:
        return HttpResponse(status=401)
    
    # Check if the content_type_id and object_id are provided
    if not content_type_id or not object_id:
        return HttpResponse(status=400)


    if request.method == 'POST':
        if not request.user.has_perm('bloomerp.add_bookmark'):
            return HttpResponse(status=403)

        # Check if the bookmark allready exists
        # If it does, delete it
        # If it does not, create it
        bookmark = Bookmark.objects.filter(user=user, content_type_id=content_type_id, object_id=object_id)
        if bookmark.exists():
            bookmark.delete()
            bookmarked = False
        else:
            Bookmark.objects.create(user=user, content_type_id=content_type_id, object_id=object_id)
            bookmarked = True
    else:
        # Permissions check
        if not user.has_perm('bloomerp.view_bookmark'):
            return HttpResponse('Permission denied', status=403)


        # Get all bookmarks for the user
        bookmarks = Bookmark.objects.filter(user=user)
        # Get the bookmark for the current object
        bookmark = bookmarks.filter(content_type_id=content_type_id, object_id=object_id)

        if bookmark.exists():
            bookmarked = True
        else:
            bookmarked = False


    context = {
        'bookmarked': bookmarked,
        'content_type_id': content_type_id,
        'object_id': object_id,
        'target' : request.htmx.target,
        'size': size
    }
    return render(request, 'components/bookmark.html', context)