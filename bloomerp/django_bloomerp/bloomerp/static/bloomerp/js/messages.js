function showMessage(text, type) {
    // Create a new message container
    const messageContainer = document.createElement('div');
    messageContainer.classList.add('message-container', 'shadow');

    // Add specific class based on the type
    if (type === 'error') {
        messageContainer.classList.add('alert-message-error');
    } else if (type === 'success') {
        messageContainer.classList.add('alert-message-success');
    } else if (type === 'info') {
        messageContainer.classList.add('alert-message-info');
    } else if (type === 'warning') {
        messageContainer.classList.add('alert-message-warning');
    }

    // Create the inner message content
    const messageContent = document.createElement('div');
    messageContent.classList.add('alert-message');
    messageContent.innerHTML = `
        <img src="/static/bloomerp/icons/${type}.svg" class="alert-icon">
        <div>${text}</div>
        <img src="/static/bloomerp/icons/close.svg" alt="X" width="20" height="20" class="alert-close">
    `;

    // Append the content to the container
    messageContainer.appendChild(messageContent);

    // Append the container to the messages wrapper
    const messagesWrapper = document.querySelector('.messages-wrapper');
    if (messagesWrapper) {
        messagesWrapper.appendChild(messageContainer);
    } else {
        console.error('Messages wrapper element not found');
        return;
    }

    // Add event listener for the close icon
    messageContent.querySelector('.alert-close').addEventListener('click', function () {
        messageContainer.remove();
    });

    // Set a timeout to add the fade-out class after 10 seconds
    setTimeout(function () {
        messageContainer.classList.add('fade-out');
    }, 10000);

    // Listen for the end of the transition to remove the message from the DOM
    messageContainer.addEventListener('transitionend', function (event) {
        if (event.propertyName === 'opacity' && messageContainer.classList.contains('fade-out')) {
            messageContainer.remove();
        }
    });
}