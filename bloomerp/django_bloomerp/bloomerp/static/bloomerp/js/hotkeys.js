// Search
document.addEventListener('DOMContentLoaded', function() {
    // Ctrl + Q to focus on search input
    document.addEventListener('keydown', function(event) {
        if (event.ctrlKey && event.key === 'q' || event.ctrlKey && event.key === 'Q') {
            event.preventDefault();
            const inputField = document.getElementById('searchInput');
            if (inputField) {
                inputField.focus();
                const dropdown = new bootstrap.Dropdown(inputField);
                dropdown.toggle();
            }
        }
    });

    // Ctrl + B to toggle sidebar
    document.addEventListener('keydown', function(event) {
        if (event.ctrlKey && event.key === 'b') {
            event.preventDefault();

            const sidebar = document.getElementById('bloomerpBody');
            if (sidebar) {
                sidebar.classList.toggle('toggle-sidebar');
            }
        }
    });
});