function openModal(modalId) {
    const backdrop = document.getElementById(modalId + '-backdrop');
    const container = document.getElementById(modalId + '-container');
    
    if (backdrop && container) {
        backdrop.classList.remove('hidden');
        backdrop.classList.add('flex');
        
        // Add animation
        setTimeout(() => {
            container.classList.add('scale-100', 'opacity-100');
            container.classList.remove('scale-95', 'opacity-0');
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
        container.classList.add('scale-95', 'opacity-0');
        container.classList.remove('scale-100', 'opacity-100');
        
        setTimeout(() => {
            backdrop.classList.add('hidden');
            backdrop.classList.remove('flex');
            
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
    const modalContainers = document.querySelectorAll('[id$="-container"]');
    modalContainers.forEach(container => {
        container.classList.add('scale-95', 'opacity-0');
    });
});