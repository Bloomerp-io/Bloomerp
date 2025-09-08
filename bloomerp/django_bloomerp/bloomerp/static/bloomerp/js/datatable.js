function getDataTableUrl(dataTableId) {
    return document.getElementById(dataTableId + '-datatable-url').value;
}

function reloadTable(dataTableId, request_params, url) {
    htmx.ajax(
        'GET',
        `${url}?${request_params}`,
        `#${dataTableId}`
        );
}

function reloadDataTable(dataTableId) {
    // Reloads a datatable using just the datatable Id

    let url = getDataTableUrl(dataTableId);
    htmx.ajax('GET', url, `#${dataTableId}`);
}

function addContextMenu(datatableId) {
    table = document.getElementById(datatableId);
    contextMenu = document.getElementById(datatableId+'-context-menu');

    let currentCell;

    table.querySelectorAll('td').forEach(cell => {
        // Check if the cell has allow-context-menu attribute
        if (!cell.hasAttribute('allow-context-menu')) {
            return;
        }

        cell.addEventListener('contextmenu', function(e) {
            e.preventDefault();
            currentCell = cell;

            // Get the window width and height
            const tableRect = table.getBoundingClientRect();

            // Calculate click position relative to the table's top-left corner
            const relativeX = e.clientX - tableRect.left;
            const relativeY = e.clientY - tableRect.top;

            // Prevent overflow (optional)
            const menuWidth = contextMenu.offsetWidth;
            const menuHeight = contextMenu.offsetHeight;

            const tableWidth = tableRect.width;
            const tableHeight = tableRect.height;

            // Adjust to avoid overflow inside the table
            const adjustedX = (relativeX + menuWidth > tableWidth) 
                                ? tableWidth - menuWidth - 10 
                                : relativeX;

            const adjustedY = (relativeY + menuHeight > tableHeight) 
                                ? tableHeight - menuHeight - 10 
                                : relativeY;

            // Position the context menu
            contextMenu.style.left = `${adjustedX}px`;
            contextMenu.style.top = `${adjustedY + 120}px`;
            contextMenu.style.display = 'block';

            // If cell has no context-menu-filter-value attribute, hide the filter option
            if (!cell.hasAttribute('context-menu-filter-value')) {
                document.getElementById(datatableId+'-context-menu-filter-value-list-item').style.display = 'none';
            } else {
                document.getElementById(datatableId+'-context-menu-filter-value-list-item').style.display = 'block';
            }

        });
    });

    document.addEventListener('click', function() {
        contextMenu.style.display = 'none';
    });

    document.getElementById(datatableId+'-context-menu-copy-value').addEventListener('click', function(e) {
        e.preventDefault();
        navigator.clipboard.writeText(currentCell.textContent);
        contextMenu.style.display = 'none';
        showMessage('Value copied to clipboard','info');
    });

    document.getElementById(datatableId+'-context-menu-filter-value').addEventListener('click', function(e) {
        e.preventDefault();
        // Implement your filtering logic here
        contextMenu.style.display = 'none';
        const filterValue = currentCell.getAttribute('context-menu-filter-value');

        // Ensure the filter value is not already applied
        if (!currentCell.classList.contains('filtered')) {
            filterDataTable(filterValue, datatableId);
            currentCell.classList.add('filtered');
        } else {
            return
        }
    });
}

function filterDataTable(filter, datatableId) {
    let url = getDataTableUrl(datatableId);

    htmx.ajax(
        'GET',
        `${url}&${filter}`,
        `#${datatableId}`
        );

    showMessage('Datatable filtered','info');
}