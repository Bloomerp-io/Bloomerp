
function getFileTableObjectId() {
    let objectId = document.getElementById('file_table_object_id').value;
    if (objectId === '') {
        objectId = null;
    }
    return objectId;
}

function getFileTableTarget() {
    let target = document.getElementById('file_table_target').value;
    if (target === '') {
        target = null;
    }
    return target;
}

function getFileTableContentTypeId() {
    let contentTypeId = document.getElementById('file_table_content_type_id').value;
    if (contentTypeId === '') {
        contentTypeId = null;
    }
    return contentTypeId;
}

function getFileTableCurrentFolderId() {
    let currentFolderId = document.getElementById('file_table_current_folder_id').value;
    if (currentFolderId === '') {
        currentFolderId = null;
    }
    return currentFolderId;
}

function getFileTableCurrentUrl() {
    return document.getElementById('file_table_url').value;
}

function getFileTableUserId() {
    return document.getElementById('file_table_user_id').value;
}

function getFileFolderApiUrl() {
    return document.getElementById('file_table_folder_api_url').value;
}

function getFileTableSort() {
    return document.getElementById('file_table_sort').value;
}

function getFileApiUrl() {
    return document.getElementById('file_table_file_api_url').value;
}

function getCsrfToken() {
    return document.getElementById('csrf_token').value;
}

// Dragging a new file onto the table
function isFileDragged(event) {
    // Check if the item being dragged is a file
    return event.dataTransfer.types.includes('Files');
}

function isDroppedOnFolder(event) {
    // Checks if item is being dropped on a folder
    return event.target.parentElement.classList.contains('folder-row');
}

function folderDroppedOnFolder(event) {
    // Checks if item is being dropped on a folder
    return event.target.parentElement.classList.contains('folder-row');
}


function fileDragStartHandler(event) {
    // Get the nearest parent element with the data-id attribute
    let fileElement = event.target.closest('[data-id]');
    let fileId = fileElement ? fileElement.getAttribute('data-id') : null;

    // Set the data transfer with type identifier
    event.dataTransfer.setData('text/plain', JSON.stringify({ type: 'file', id: fileId }));
}

function folderDragStartHandler(event) {
    // Get the id of the folder
    var folderId = event.target.getAttribute('id').split('_')[1];

    // Set the data transfer with type identifier
    event.dataTransfer.setData('text/plain', JSON.stringify({ type: 'folder', id: folderId }));
}


// Table handlers
async function tableDropHandler(event) {
    event.preventDefault();
    var currentFolder = getFileTableCurrentFolderId();

    document.getElementById('fileTableBody').classList.remove('bg-primary-light');

    if (isDroppedOnFolder(event)) {
        return;
    }

    if (isFileDragged(event)) {
        var files = event.dataTransfer.files;
        for (var i = 0; i < files.length; i++) {
            await uploadFile(files[i], currentFolder);
        }
        
        refreshFiles(getFileTableTarget());
        if (files.length > 1) {
            showMessage(`${files.length} files uploaded successfully`, 'success');
        } else {
            showMessage('File uploaded successfully', 'success');
        }
        
    }
}


function tableDragoverHandler(event) {
    // Prevent default behavior (Prevent the file from being opened)
    event.preventDefault();
    
    if (isFileDragged(event)) {
        document.getElementById('fileTableBody').classList.add('bg-primary-light');
    }

}

function tableDragleaveHandler(event) {
    // Prevent default behavior (Prevent the file from being opened)
    event.preventDefault();
    document.getElementById('fileTableBody').classList.remove('bg-primary-light');
}


// Folder handlers
function folderDragOverHandler(event) {
    // Prevent default behavior (Prevent the file from being opened)
    event.preventDefault();

    // Add class to show that the folder can be dropped
    event.target.parentElement.classList.add('bg-primary-light');
}

function folderDragLeaveHandler(event) {
    // Remove class to show that the folder can be dropped
    event.target.parentElement.classList.remove('bg-primary-light');
}

async function folderDropHandler(event) {
    event.preventDefault();
    event.target.parentElement.classList.remove('bg-primary-light');
    var targetFolderId = event.target.parentElement.getAttribute('id').split('_')[1];
    var currentFolder = getFileTableCurrentFolderId();


    var data = JSON.parse(event.dataTransfer.getData('text/plain'));

    if (data.type === 'folder') {
        if (data.id == targetFolderId) {
            return;
        }
        await addFolderToFolder(data.id, targetFolderId);
        refreshFiles(getFileTableTarget());
        showMessage('Folder moved successfully', 'success');
    } else if (data.type === 'file') {
        console.log('File dropped on folder');
        await addFileToFolder(data.id, targetFolderId);

        if (currentFolder) {
            // Remove the file from the current folder
            await removeFileFromFolder(data.id, currentFolder);
        }

        refreshFiles(getFileTableTarget());
        showMessage('File added to folder', 'success');
    }
}

// Function to upload a file
async function uploadFile(fileData, folderId) {
    // Get content_type_id, object_id and current_folder
    let content_type_id = getFileTableContentTypeId();
    let object_id = getFileTableObjectId();
    let created_by = getFileTableUserId();
    let updated_by = created_by;        
    
    var formData = new FormData();

    // Append all of the data to the form
    formData.append('file', fileData);

    // if content_type_id is an integer, append it to the form
    if (!isNaN(content_type_id)) {
        formData.append('content_type', content_type_id);
    }
    if (!isNaN(object_id)) {
        formData.append('object_id', object_id);
    }

    formData.append('created_by', created_by);
    formData.append('updated_by', updated_by);

    // Upload the file
    try {
        let response = await fetch(getFileApiUrl(), {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCsrfToken()
            },
            body: formData
        });
        let data = await response.json();
        let newFileId = data.id;

        if (folderId) {
            await addFileToFolder(newFileId, folderId);
        }
    } catch (error) {
        showMessage(`Error uploading file: ${error}`, 'danger');
    }
}

async function deleteFile(fileId) {
        // Set the delete url
        url = getFileApiUrl() + fileId + '/';

        // Set the form action
        await fetch(url, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            }}
        )

    }


// Function to add a file to a folder
async function addFileToFolder(fileId, folderId) {
    let listUrl = getFileFolderApiUrl();
    let url = listUrl + folderId + '/';

    try {
        let response = await fetch(url);
        let data = await response.json();
        data.files.push(fileId);

        await fetch(url, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify(data)
        });
    } catch (error) {
        console.error('Error:', error);
    }
}

async function removeFileFromFolder(fileId, folderId) {
    let listUrl = getFileFolderApiUrl();
    let url = listUrl + folderId + '/';

    try {
        let response = await fetch(url);
        let data = await response.json();
        data.files = data.files.filter(file => file != fileId);

        await fetch(url, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify(data)
        });
    } catch (error) {
        console.error('Error:', error);
    }
}

async function addFolderToFolder(folderId, parentFolderId) {
    let listUrl = getFileFolderApiUrl();
    let url = listUrl + folderId + '/';

    if (folderId == parentFolderId) {
        return;
    }

    try {
        let response = await fetch(url);
        let data = await response.json();
        data.parent = parentFolderId;

        await fetch(url, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify(data)
        });
    } catch (error) {
        console.error('Error:', error);
    }
}


// Function to refresh files
function refreshFiles(target) {
    if (!target) {
        target = "#file_list";
    }
    
    setTimeout(() => {
        htmx.ajax('GET', getFileTableCurrentUrl(), target);
    }, 1000);

}

// If an item is selected, bulk actions should be shown
document.addEventListener('change', function (event) {
    if (event.target.name == 'selected_files') {
        let checkboxes = document.getElementsByName('selected_files');
        let bulkActions = document.getElementById('bulk-actions');
        let checked = false;
        for (let i = 0; i < checkboxes.length; i++) {
            if (checkboxes[i].checked) {
                checked = true;
                break;
            }
        }
        if (checked) {
            bulkActions.classList.remove('hidden');
        } else {
            bulkActions.classList.add('hidden');
        }
        //updateSelectedObjectsCount();
        addSelectedObjectsToForm();
    }
});

// Select all files & folders
function selectAll(source) {
    let checkboxes = document.getElementsByName('selected_files');
    let bulkActions = document.getElementById('bulk-actions');
    for (let i = 0, n = checkboxes.length; i < n; i++) {
        checkboxes[i].checked = source.checked;
    }
    // Show or hide bulk actions based on the state of the checkboxes
    if (source.checked) {
        bulkActions.classList.remove('hidden');
    } else {
        bulkActions.classList.add('hidden');
    }
    //updateSelectedObjectsCount();
    addSelectedObjectsToForm();
}

// Sort functionality
function sortFiles(sortBy) {
    let allreadySorted = getFileTableSort();
    
    if (allreadySorted == sortBy) {
        sortBy = '-' + sortBy;
    }

    url = getFileTableCurrentUrl();

    target = getFileTableTarget();

    // Check if the url already has contains ?
    if (url.includes('?')) {
        url += '&sort=' + sortBy;
    } else {
        url += '?sort=' + sortBy;
    }
    htmx.ajax('GET',url, target);
}

// Get selected objects
function addSelectedObjectsToForm() {
    // Add selected object ids to the bulk update and delete forms
    let checkboxes = document.getElementsByName('selected_files');
    let objectIds = [];
    for (let i = 0; i < checkboxes.length; i++) {
        if (checkboxes[i].checked) {
            objectIds.push(checkboxes[i].value);
        }
    }
    
    //document.getElementById('bulkUpdateIds').innerHTML = objectIds.map(id => `<input type="hidden" name="object_ids" value="${id}">`).join('');
    document.getElementById('bulkDeleteIds').innerHTML = objectIds.map(id => `<input type="hidden" name="object_ids" value="${id}">`).join('');
}

// Add event listener to the bulk delete form
document.addEventListener('htmx:afterRequest', function (event) {
    method = event.detail.requestConfig.verb;

    if (method == 'post' || method == 'delete') {
        refreshFiles(getFileTableTarget());
    }
});



