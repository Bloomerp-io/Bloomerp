from bloomerp.utils.router import route
from django.shortcuts import render
from django.http import HttpResponse, HttpRequest
from bloomerp.models import File, FileFolder, AbstractBloomerpUser
from django.contrib.contenttypes.models import ContentType
from bloomerp.forms.core import BloomerpModelForm
from django.forms.models import modelform_factory
from bloomerp.utils.filters import dynamic_filterset_factory
from django.contrib.auth.decorators import login_required

@login_required
@route('files')
def files(request: HttpRequest) -> HttpResponse:
    '''
    Component for rendering a list of files and folders.
    The files can be filtered by content type, object id, and folder.
    
    Variables:
    - content_type_id: The content type id related to the file.
    - object_id: The object id related to the file.
    - query: A search query to filter files by name.
    - folder_id: The folder id to filter files by folder.
    - sort: The field to sort files by.

    '''
    # Some logic for permissions here
    if not request.user.has_perm('bloomerp.view_file'):
        return HttpResponse('User does not have permission to view files')

    # get the accessible content types for the user
    user : AbstractBloomerpUser = request.user
    accessible_content_types = user.get_content_types_for_user('view')


    # initialize variables
    content_type_id = request.GET.get('content_type_id', None)
    object_id = request.GET.get('object_id', None)
    query = request.GET.get('query', None)
    folder_id = request.GET.get('folder_id', None)
    sort = request.GET.get('sort', None)
    target = request.htmx.target


    # Convert empty strings to None
    if content_type_id in ['', 'None']:
        content_type_id = None
    if object_id in ['', 'None']:
        object_id = None
    if folder_id in ['', 'None']:
        folder_id = None
    if sort == '':
        sort = None

    FilterSet = dynamic_filterset_factory(File)

    # Initialize create folder form
    create_folder_form = modelform_factory(FileFolder, form=BloomerpModelForm, fields=['name', 'content_types'])(model=FileFolder, user=request.user, initial={'content_types': [content_type_id] if content_type_id else None})

    # First, we check if the user is trying to filter by folder
    if folder_id:
        try:
            folder = FileFolder.objects.get(id=folder_id)
            # If the user is filtering by folder, we only show files in that folder
            files = folder.files.all()

            # Filter files by content type and object id if they are provided
            if object_id:
                files = files.filter(object_id=object_id)

            # Filter files by query if it exists
            if query:
                files = files.filter(name__icontains=query)

            # Get all folders within the current folder
            folders = FileFolder.objects.filter(parent=folder).order_by('name')

            # Create update folder form
            update_folder_form = modelform_factory(FileFolder, form=BloomerpModelForm, fields=['name', 'content_types'])(model=FileFolder, user=request.user, instance=folder)

            if content_type_id:
                folders = folders.filter(content_types__in=[content_type_id])

        except FileFolder.DoesNotExist:
            # Handle the case where the folder does not exist
            folders = FileFolder.objects.none()  # or some other error handling logic
    else:
        # If no folder_id is specified, fetch root-level folders (parent=None)
        folders = FileFolder.objects.filter(parent=None)

        if content_type_id:
            folders = folders.filter(content_types__in=[content_type_id])
            

        update_folder_form = None

        # If the user is not filtering by folder, we show all files, optionally filtering by query
        if query:
            files = File.objects.filter(name__icontains=query)
        else:
            files = File.objects.all()

        # Filter files by content type and object id if they are provided
        if content_type_id:
            files = files.filter(content_type_id=content_type_id)

        if object_id:
            files = files.filter(object_id=object_id)

        # Exclude files that are in a folder
        files = files.filter(folders=None)

    # Sort files by name if sort is not specified
    if not sort:
        files = files.order_by('name')
    elif sort:
        try:
        # Sort files by name in ascending order
            files = files.order_by(sort)
            folders = folders.order_by(sort)
        except ValueError:
            # Handle the case where the sort parameter is invalid
            pass
    
    # Add the current url to the context
    url = request.path
    
    if folder_id or content_type_id or object_id:
        url += '?'  # Add a ? to the url if there are any query parameters
    if folder_id:
        url += f'folder_id={folder_id}'
    if content_type_id:
        url += f'&content_type_id={content_type_id}'
    if object_id:
        url += f'&object_id={object_id}'
    
    # Filter files by content type and object id if they are provided
    filterset = FilterSet(request.GET, queryset=files) # Initialize files as empty queryset in case it's not used later
    files = filterset.qs

    # Filter on accessible content types, including files that are not mapped to a content type
    files = files.filter(content_type_id__in=accessible_content_types) | files.filter(content_type_id__isnull=True)

    context = {
        'files': files,
        'folders': folders,
        'current_folder': folder if folder_id else None,
        'sort': sort,
        'content_type_id': content_type_id,
        'object_id': object_id,
        'file_content_type_id': ContentType.objects.get_for_model(File).id,
        'url': url,
        'update_folder_form': update_folder_form,
        'create_folder_form': create_folder_form,
        'target': target,
        }
    return render(request, 'components/files.html', context)
