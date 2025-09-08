// Modal functionality for Bloomerp UI

function openModal(modalId) {
    const backdrop = document.getElementById(modalId + '-backdrop');
    const container = document.getElementById(modalId + '-container');
    
    if (backdrop && container) {
        // Display the backdrop
        backdrop.classList.remove('hidden');
        backdrop.classList.add('flex');
        
        // Add animation with a slight delay to ensure the display change is processed
        setTimeout(() => {
            container.classList.remove('scale-95', 'opacity-0');
            container.classList.add('scale-100', 'opacity-100');
        }, 10);
        
        // Prevent body scroll
        document.body.style.overflow = 'hidden';
        
        // Focus trap (simple implementation)
        container.focus();
    }
}

function closeModal(modalId) {
    const backdrop = document.getElementById(modalId + '-backdrop');
    const container = document.getElementById(modalId + '-container');
    
    if (backdrop && container) {
        // Add closing animation
        container.classList.remove('scale-100', 'opacity-100');
        container.classList.add('scale-95', 'opacity-0');
        
        // Wait for animation to complete before hiding
        setTimeout(() => {
            backdrop.classList.remove('flex');
            backdrop.classList.add('hidden');
            
            // Restore body scroll
            document.body.style.overflow = '';
        }, 200);
    }
}

// ESC key to close modal
document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
        // Close the topmost modal (if multiple are open)
        const openModals = document.querySelectorAll('[id$="-backdrop"]:not(.hidden)');
        if (openModals.length > 0) {
            const lastModal = openModals[openModals.length - 1];
            const modalId = lastModal.id.replace('-backdrop', '');
            closeModal(modalId);
        }
    }
});

// Initialize modal animations
document.addEventListener('DOMContentLoaded', function() {
    // No need for additional initialization as the initial state is now set in the HTML
    // This ensures modals start in the correct visual state
    
    // Set up global event listeners for accessibility
    setupModalAccessibility();
});

// Toggle modal between normal and fullscreen mode
function toggleModalFullscreen(modalId) {
    const container = document.getElementById(modalId + '-container');
    const backdrop = document.getElementById(modalId + '-backdrop');
    const expandIcon = container.querySelector('.fullscreen-expand');
    const collapseIcon = container.querySelector('.fullscreen-collapse');
    
    if (container && backdrop) {
        // Check if modal is currently in fullscreen
        const isFullscreen = container.classList.contains('max-w-full') && 
                            container.classList.contains('w-full') && 
                            container.classList.contains('h-full') &&
                            container.classList.contains('rounded-none');
        
        if (isFullscreen) {
            // Restore to original size
            container.classList.remove('max-w-full', 'w-full', 'h-full', 'rounded-none');
            
            // Add back the original size class based on the size attribute
            const size = container.getAttribute('data-size') || 'md';
            if (size === 'sm') {
                container.classList.add('max-w-sm');
            } else if (size === 'lg') {
                container.classList.add('max-w-4xl');
            } else if (size === 'xl') {
                container.classList.add('max-w-6xl');
            } else {
                container.classList.add('max-w-2xl');
            }
            
            // Update icons
            if (expandIcon && collapseIcon) {
                expandIcon.classList.remove('hidden');
                collapseIcon.classList.add('hidden');
            }
            
            // Update modal body max height
            const modalBody = document.getElementById(modalId + '-modal-body');
            if (modalBody) {
                modalBody.classList.remove('flex-1');
                modalBody.classList.add('max-h-96');
            }
        } else {
            // Store original size
            const sizeClasses = ['max-w-sm', 'max-w-2xl', 'max-w-4xl', 'max-w-6xl'];
            let currentSize = 'md';
            
            sizeClasses.forEach(sizeClass => {
                if (container.classList.contains(sizeClass)) {
                    container.classList.remove(sizeClass);
                    if (sizeClass === 'max-w-sm') currentSize = 'sm';
                    else if (sizeClass === 'max-w-4xl') currentSize = 'lg';
                    else if (sizeClass === 'max-w-6xl') currentSize = 'xl';
                }
            });
            
            // Store the original size for later restoration
            container.setAttribute('data-size', currentSize);
            
            // Set fullscreen
            container.classList.add('max-w-full', 'w-full', 'h-full', 'rounded-none');
            
            // Update icons
            if (expandIcon && collapseIcon) {
                expandIcon.classList.add('hidden');
                collapseIcon.classList.remove('hidden');
            }
            
            // Update modal body height
            const modalBody = document.getElementById(modalId + '-modal-body');
            if (modalBody) {
                modalBody.classList.remove('max-h-96');
                modalBody.classList.add('flex-1');
            }
        }
    }
}

// Setup accessibility features for modals
function setupModalAccessibility() {
    // Focus trap for modals - capture tab navigation
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Tab') {
            const openModals = document.querySelectorAll('[id$="-backdrop"]:not(.hidden)');
            if (openModals.length > 0) {
                const lastModal = openModals[openModals.length - 1];
                const modalId = lastModal.id.replace('-backdrop', '');
                const container = document.getElementById(modalId + '-container');
                
                if (container) {
                    const focusableElements = container.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
                    if (focusableElements.length > 0) {
                        const firstElement = focusableElements[0];
                        const lastElement = focusableElements[focusableElements.length - 1];
                        
                        if (event.shiftKey && document.activeElement === firstElement) {
                            event.preventDefault();
                            lastElement.focus();
                        } else if (!event.shiftKey && document.activeElement === lastElement) {
                            event.preventDefault();
                            firstElement.focus();
                        }
                    }
                }
            }
        }
    });
}