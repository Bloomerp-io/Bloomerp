function createAlertTitle(title: string): HTMLElement {
    const titleElement = document.createElement("p");
    titleElement.className = "font-medium";
    titleElement.textContent = title;
    return titleElement;
}

function createAlertMessage(message: string): HTMLElement {
    const messageElement = document.createElement("p");
    messageElement.className = "text-sm";
    messageElement.textContent = message;
    return messageElement;
}

export function createInlineAlert(message: string, title = ""): HTMLElement {
    const alert = document.createElement("div");
    alert.className = "rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-red-700";

    if (title.trim()) {
        alert.appendChild(createAlertTitle(title));
    }

    alert.appendChild(createAlertMessage(message));
    return alert;
}

export function renderInlineAlert(target: HTMLElement | null, message: string, title = ""): void {
    if (!target) {
        return;
    }

    target.innerHTML = "";
    target.appendChild(createInlineAlert(message, title));
}

export function clearInlineAlert(target: HTMLElement | null): void {
    if (!target) {
        return;
    }

    target.innerHTML = "";
}
