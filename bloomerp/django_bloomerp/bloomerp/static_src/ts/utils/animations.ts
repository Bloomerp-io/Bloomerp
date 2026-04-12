
/**
 * Function that inserts a skeleton into the target element.
 * It relies on CSS styling that can be found in the project's stylesheet.
 * 
 * @param target The HTMLElement where the skeleton will be inserted
 */
function insertSkeleton(target: HTMLElement) {
    // Create skeleton element
    const skeleton = document.createElement('div');
    skeleton.className = 'skeleton-loader';
    skeleton.innerHTML = `
    <div class="w-full">
        <div class="skeleton-header"></div>
        <div class="skeleton-content">
            <div class="skeleton-line"></div>
            <div class="skeleton-line"></div>
            <div class="skeleton-line short"></div>
        </div>
    </div>
    `;

    // Clear target
    target.innerHTML = '';

    // If target is a tbody, wrap skeleton in a row and cell
    if (target.tagName === 'TBODY') {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 100; // Span all columns
        cell.appendChild(skeleton);
        row.appendChild(cell);
        target.appendChild(row);
    } else {
        target.appendChild(skeleton);
    }
}

export { insertSkeleton };