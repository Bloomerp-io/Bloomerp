import htmx from "htmx.org";

// The query selector attribute
export const componentIdentifier = 'bloomerp-component'

class BaseComponent {
    public element: HTMLElement | null = null;

    constructor(element?: HTMLElement) {
        if (element) {
            this.element = element;
            this.initialize();
        }
    }

    /**
     * Override this method in your component
     * This is where you put your component logic
     */
    public initialize(): void {
        // Override this method in your component
    }

    /**
     * Cleanup method - override if you need to clean up event listeners, etc.
     */
    public destroy(): void {
        // Override this method if needed
    }
}

// Registry to store all component classes
const componentRegistry = new Map<string, new (element: HTMLElement) => BaseComponent>();

// Registry to store component instances by their root element
const componentInstanceRegistry = new WeakMap<HTMLElement, BaseComponent>();

/**
 * Register a component class
 * @param componentId - The ID used in attribute
 * @param componentClass - The component class constructor
 */
export function registerComponent(
    componentId: string,
    componentClass: new (element: HTMLElement) => BaseComponent
): void {
    componentRegistry.set(componentId, componentClass);
}

/**
 * Initialize all components in the DOM
 * Looks for elements with attribute and instantiates them
 */
export function initComponents(container: Document | HTMLElement = document): void {
    const elements = container.querySelectorAll<HTMLElement>(`[${componentIdentifier}]`);
    
    elements.forEach((element) => {
        const componentId = element.getAttribute(componentIdentifier);
        
        if (!componentId) {
            console.warn(`Element has ${componentIdentifier} attribute but no ID:`, element);
            return;
        }

        const ComponentClass = componentRegistry.get(componentId);
        
        if (!ComponentClass) {
            console.warn(`No component registered for ID: ${componentId}`);
            return;
        }

        // Avoid double initialization based on the actual instance registry.
        // IMPORTANT: `data-component-initialized` can be stale when HTML is
        // restored from history (HTMX history cache / browser bfcache).
        if (componentInstanceRegistry.get(element)) return;

        try {
            // Instantiate the component
            const instance = new ComponentClass(element);

            // Store instance for lookups (e.g. getComponent)
            componentInstanceRegistry.set(element, instance);
            
            // Mark as initialized
            element.setAttribute('data-component-initialized', 'true');
        } catch (error) {
            console.error(`Error initializing component ${componentId}:`, error);
        }
    });
}

/**
 * Initialize components on DOM ready and after HTMX swaps
 */
export function setupComponentAutoInit(): void {
    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => initComponents());
    } else {
        // DOM already loaded
        initComponents();
    }

    // Initialize after HTMX swaps (if HTMX is present)
    if (typeof htmx !== 'undefined') {
        document.body.addEventListener('htmx:afterSwap', (event: Event) => {
            const customEvent = event as CustomEvent;
            const target = (customEvent.detail?.target ?? null) as HTMLElement | null;

            // With `hx-swap="outerHTML"`, the original target element may have been
            // replaced/detached by the time this handler runs. In that case, scanning
            // inside `target` won't find the newly-inserted DOM.
            const container: Document | HTMLElement = target && target.isConnected ? target : document;

            initComponents(container);
        });

        // When navigating back/forward with HTMX history, the DOM can be restored
        // without an afterSwap on the right container. Re-scan the document.
        document.body.addEventListener('htmx:historyRestore', () => {
            initComponents(document);
        });
    }

    // When the browser restores a page from the back-forward cache (bfcache),
    // DOMContentLoaded won't fire again. Re-init components on pageshow.
    window.addEventListener('pageshow', () => {
        initComponents(document);
    });
}

/**
 * Returns the component representation of an element
 * @param element The html element
 * @returns the component (subclass of BaseComponent if found)
 */
export function getComponent(element:HTMLElement) : BaseComponent | null {
    if (!element || !element.hasAttribute(componentIdentifier)) return null;

    const existing = componentInstanceRegistry.get(element);
    if (existing) return existing;

    // Lazy-init: if the element declares a component but hasn't been instantiated yet,
    // create it on-demand.
    const componentId = element.getAttribute(componentIdentifier);
    if (!componentId) return null;

    const ComponentClass = componentRegistry.get(componentId);
    if (!ComponentClass) return null;

    try {
        const instance = new ComponentClass(element);
        componentInstanceRegistry.set(element, instance);
        element.setAttribute('data-component-initialized', 'true');
        return instance;
    } catch (error) {
        console.error(`Error lazily initializing component ${componentId}:`, error);
        return null;
    }
}

export default BaseComponent;