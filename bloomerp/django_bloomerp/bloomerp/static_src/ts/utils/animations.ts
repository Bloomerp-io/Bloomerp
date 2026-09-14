
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

/**
 * Inserts a compact loading indicator that cycles from one dot to three dots.
 *
 * @param target The HTMLElement where the loading indicator will be inserted
 */
function insertLoadingDots(target: HTMLElement) {
    const loadingDots = document.createElement('span');
    loadingDots.className = 'inline-flex min-h-6 items-center justify-center text-lg text-gray-500';
    loadingDots.setAttribute('aria-label', 'Loading');
    loadingDots.setAttribute('role', 'status');
    loadingDots.setAttribute('hx-history', 'false');

    let dotCount = 1;
    loadingDots.textContent = '.'.repeat(dotCount);
    const intervalId = window.setInterval(() => {
        dotCount = dotCount === 3 ? 1 : dotCount + 1;
        loadingDots.textContent = '.'.repeat(dotCount);
    }, 350);
    target.addEventListener('htmx:beforeSwap', () => window.clearInterval(intervalId), { once: true });

    target.innerHTML = '';
    target.appendChild(loadingDots);
}

function insertAnimation(target: HTMLElement, animation: string | null) {
    switch (animation?.trim().toLowerCase()) {
        case 'dot-dot-dot':
        case 'dots':
            insertLoadingDots(target);
            break;
        default:
            insertSkeleton(target);
    }
}


export function SetupAnimationListener() {
    document.addEventListener('htmx:beforeSend', (ev) => {
        const sourceElement = ev.target as HTMLElement

        if (!sourceElement.hasAttribute('hx-animation')) {return}
        if (!sourceElement.hasAttribute('hx-target')) {return}

        const targetSelector = sourceElement.getAttribute('hx-target');
        const target = targetSelector === 'this'
            ? sourceElement
            : document.querySelector(targetSelector ?? '') as HTMLElement | null;
        if (!target) return;

        insertAnimation(target, sourceElement.getAttribute('hx-animation'))
    })
}


export { insertSkeleton };
