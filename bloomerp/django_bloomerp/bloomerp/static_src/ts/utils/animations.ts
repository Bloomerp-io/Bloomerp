
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
    // Keep the loader readable even when it is rendered outside the element
    // that owns the theme class (for example, in a table body or drawer).
    if (target.closest('.dark') || document.documentElement.classList.contains('dark')) {
        skeleton.classList.add('skeleton-loader--dark');
    }
    // The loader is transient UI, not a valid page snapshot. If this request
    // pushes a URL, make HTMX fetch the outgoing page again rather than cache
    // and later restore the skeleton as its history content.
    skeleton.setAttribute('hx-history', 'false');
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


export function SetupAnimationListener() {
    document.addEventListener('htmx:beforeSend', (ev) => {
        const sourceElement = ev.target as HTMLElement

        if (!sourceElement.hasAttribute('hx-animation')) {return}
        if (!sourceElement.hasAttribute('hx-target')) {return}

        let target = document.querySelector(sourceElement.getAttribute('hx-target')) as HTMLElement

        insertSkeleton(target)
    })
}


export { insertSkeleton };
