function addDragEventListeners(element) {
    // Add the drag event listeners to the element
    element.addEventListener('dragstart', onDragStart);
    element.addEventListener('dragover', onDragOver);
    element.addEventListener('drop', onDrop);
    element.addEventListener('dragleave', onDragLeave);
    element.addEventListener('contextmenu', onRightClick);

    // Make the element draggable
    element.setAttribute('draggable', 'true');
}

function onDragStart(event) {
    // Get the id of the card inside the dragable element
    const cardID = document.getElementById(event.target.id).querySelector('.card').id;

    if (cardID == null) {
        // Check if it's a new widget that is being dragged
        // Check if element id starts with 'new_widget'
        if (event.target.id.startsWith('new_widget')) {
            // Get the widget id
            const cardID = event.target.id.split('_')[2];
        } else {
            return;
        }
    }

    event.dataTransfer.setData('text/plain', cardID);
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.dropEffect = 'move';
}

function onDragOver(event) {
    // Prevent default behavior to allow drop
    event.preventDefault();
    event.target.classList.add('dragover');
}

function onDragLeave(event) {
    // Remove the class when the element leaves the drop zone
    event.target.classList.remove('dragover');
}

function onDrop(event) {
    // Prevent the default behavior
    event.preventDefault();

    // Remove the class when the element is dropped
    event.target.classList.remove('dragover');

    // Get the draggable element's id
    const id = event.dataTransfer.getData('text');
    const card = document.getElementById(id);

    if (!card) {
        // In this case it's a new widget that is being dropped
        // Get the widget id
        console.log(id);

        return;
    } 

    // Find the closest dropzone-col to make sure we're dropping in the correct div
    let dropzone = event.target;
    if (!dropzone.classList.contains('dropzone-col')) {
        // If the dropzone is not directly the dropzone-col, find the closest parent that is
        dropzone = dropzone.closest('.dropzone-col');
    }

    // Ensure we have a valid dropzone before proceeding
    if (!dropzone) {
        return;
    }

    // Get any card already present in the dropzone (if any)
    const dropzoneCard = dropzone.querySelector('.card');

    // If the dropzone is empty, append the draggable element
    if (!dropzoneCard) {
        dropzone.appendChild(card);
    } else {
        // If the dropzone is not empty, swap the elements
        const parent = card.parentElement;

        // Swap the cards between the original parent and the dropzone
        dropzone.appendChild(card);
        parent.appendChild(dropzoneCard);
    }

    // Clear the data from the data transfer
    event.dataTransfer.clearData();
}

function onRightClick(event) {
    // Prevent the default context menu
    event.preventDefault();

    return false
}

// --------------------------------------------
// Functions to initialize the dashboard layout
// --------------------------------------------
function changeLayout() {
    // Function that shows the change layout items

    // Get all of the rows
    const dropzoneRows = document.querySelectorAll('[id^="dropzone-row-"]');
    
    dropzoneRows.forEach((row) => {
        // Add the dropzone-row class to the row
        row.classList.toggle('dropzone-row');

        // Add dragable to the columns
        const columns = row.querySelectorAll('.dropzone-col');
        columns.forEach((col) => {
            addDragEventListeners(col);
        })

    })


    const rowFilters = document.querySelectorAll('[id^="row-filter"]');
    rowFilters.forEach((filter) => {
        filter.classList.toggle('hidden');
    })

    const columnFilters = document.querySelectorAll('[id^="column-filter"]');
    columnFilters.forEach((filter) => {
        filter.classList.toggle('hidden');
    })


    const dropzoneCols = document.querySelectorAll('.dropzone-col');
    dropzoneCols.forEach((col) => {
        col.classList.toggle('drag-over');
    })

    // Show the save layout button
    document.querySelector('.save-layout-div').classList.toggle('hidden');

    // Show the input to change the dashboard name
    document.getElementById('user_dashboard_view_name_input').classList.toggle('hidden');
    document.getElementById('user_dashboard_view_name').classList.toggle('hidden');

    // Hide the sidebar to get more space
    hideBloomerpSidebar();
}

function saveLayout(dashboard_id) {
    // Get all of the rows
    const rows = document.querySelectorAll('[id^="dashboard-row-"]:not([id*="-col-"])');

    // init data
    let data = {};
    let kpiList = []
    let layout = {};
    let layoutRowList = [];

    rows.forEach((row, index) => {
        // Get the row number
        const rowNumber = row.id.split('-')[2];
        let layoutRow = [];

        // Get all of the columns in the row
        rowCols = row.querySelectorAll('[id^="dashboard-row-' + rowNumber + '-col-"]');
        
        // Loop through the columns
        // Each column contains a card for which we need the card id
        // If the column is empty, we set the card id to null
        // Kpi cards are identified by the id starting with 'kpi-card-' followed by the card id
        rowCols.forEach((col, colIndex) => {
            const card = col.querySelector('[id^="kpi-card-"]');
            let kpiId = null;

            if (card) {
                kpiId = card.id.split('-')[2];
                kpiList.push(kpiId);
            }

            // Get the column width
            const classList = col.classList;
            let width = null;
            classList.forEach((className) => {
                if (className.startsWith('col-md')) {
                    width = className.split('-')[1];
                }
            })

            // Add the column to the layout
            layoutRow.push({
                'content': kpiId,
                'size': width
            })
        })
        
        layoutRowList.push(
            {
                'columns': layoutRow,
                'size': 12
            }
        );
    })

    layout['rows'] = layoutRowList;

    data['layout'] = layout;
    data['kpis'] = kpiList;

    // Get the dashboard name
    const dashboardName = document.getElementById('user_dashboard_view_name_input').value;
    data['name'] = dashboardName;

    // Send the layout to the server
    saveUserDashboardView(dashboard_id, data)

    // Change the dashboard name
    document.getElementById('user_dashboard_view_name').innerText = dashboardName;

    // Hide the save layout button
    changeLayout();

}


// --------------------------------------------
// Functions to add and remove rows and columns
// --------------------------------------------
function addColumn(rowNumber) {
    // Get the parent element
    const row = document.getElementById('dashboard-row-' + rowNumber);

    // Create a new row
    const newCol = document.createElement('div');
    newCol.classList.add('col');
    newCol.classList.add('dropzone-col');
    newCol.classList.add('drag-over');
    newCol.setAttribute('draggable', 'true');
    newCol.setAttribute('id', 'new-row');

    // Add the drag event listeners
    addDragEventListeners(newCol);


    // Add the new row to the parent element
    row.appendChild(newCol);
}

function removeRow(rowNumber) {
    // Get the parent element
    const row = document.getElementById('dropzone-row-' + rowNumber);
    row.remove()
}
function removeColumn(rowNumber, columnNumber) {
    // Get the parent element
    const column = document.getElementById('dashboard-row-' + rowNumber + '-col-' + columnNumber);
    column.remove()
}

// --------------------------------------------
// Function to set column width
// --------------------------------------------
function setColumnWidth(rowNumber, columnNumber, width) {
    const column = document.getElementById('dashboard-row-' + rowNumber + '-col-' + columnNumber);
    

    // Get class list of the column
    const classList = column.classList;

    // Remove any existing width class
    classList.forEach((className) => {
        if (className.startsWith('col-md')) {
            classList.remove(className);
        }
    })

    // Add the new width class
    column.classList.add('col-md-' + width);

}

// --------------------------------------------
// Function to PATCH user dashboard view
// --------------------------------------------
function saveUserDashboardView(dashboard_id, data) {
    // Send the layout to the server
    fetch(`/api/user-dashboard-views/${dashboard_id}/`, {
        method: 'PATCH',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify(data)
    })
}